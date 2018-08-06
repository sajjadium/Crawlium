#!/usr/bin/python

import re
import sys
import json
import copy
import hashlib
import base64
import traceback
import gzip
import StringIO
import urlparse
from collections import OrderedDict

def get_scriptid_from_stack_trace(stack):
    if len(stack['callFrames']) == 0:
        return None

    for f in stack['callFrames']:
        if f['functionName'].strip() == '':
            return f['scriptId']

    return f['scriptId']

def handle_request_response(method, params):
    requestId = params['requestId']

    if method == 'Network.requestWillBeSent':
        resourceUrl = params['request']['url'].strip()

        parsed_url = urlparse.urlparse(resourceUrl)

        if requestId not in resource_requests:
            resource_requests[requestId] = []

        resource_requests[requestId].append(params)
    elif method == 'Network.responseReceived':
        resourceType = params['type'].strip().lower()
        resourceUrl = params['response']['url'].strip()
        resourceMimeType = params['response']['mimeType']
        frameId = params['frameId']
        loaderId = params['loaderId']

        if requestId not in resource_requests:
            return

        resource_requests[requestId].append(params)

        resourceHeaders = []

        if resourceType == 'other' and ('javascript' in resourceMimeType or 'ecmascript' in resourceMimeType):
            resourceType = 'script'

        for i in range(1, len(resource_requests[requestId])):
            response = None

            if 'redirectResponse' in resource_requests[requestId][i]:
                response = resource_requests[requestId][i]['redirectResponse']
            elif 'response' in resource_requests[requestId][i]:
                response = resource_requests[requestId][i]['response']

            if response is not None:
                resourceHeaders.append(OrderedDict([
                    ('timestamp', resource_requests[requestId][i - 1]['wallTime']),
                    ('method', resource_requests[requestId][i - 1]['request']['method']),
                    ('status', (str(response['status']) + ' ' + response['statusText']).strip()),
                    ('url', response['url'].strip()),
                    ('request', None),
                    ('response', None)
                ]))

                if resourceHeaders[-1]['method'] == 'POST':
                    resourceHeaders[-1]['data'] = None

                    if 'postData' in resource_requests[requestId][i - 1]['request']:
                        resourceHeaders[-1]['data'] = resource_requests[requestId][i - 1]['request']['postData']

                if 'requestHeaders' in response:
                    resourceHeaders[-1]['request'] = {}

                    for name, value in response['requestHeaders'].items():
                        if not name.startswith(':'):
                            resourceHeaders[-1]['request'][name] = value
                elif 'request' in resource_requests[requestId][i - 1] and \
                     'headers' in resource_requests[requestId][i - 1]['request']:
                    resourceHeaders[-1]['request'] = {}

                    for name, value in resource_requests[requestId][i - 1]['request']['headers'].items():
                        if not name.startswith(':'):
                            resourceHeaders[-1]['request'][name] = value

                if 'headers' in response:
                    resourceHeaders[-1]['response'] = {}

                    for name, value in response['headers'].items():
                        if not name.startswith(':'):
                            resourceHeaders[-1]['response'][name] = value

        if not resourceUrl.startswith('http:') and not resourceUrl.startswith('https:'):
            resourceHeaders = None

        initiator_script_id = None
        initiator = resource_requests[requestId][0]['initiator']

        if initiator['type'].strip().lower() == 'script':
            initiator_script_id = get_scriptid_from_stack_trace(initiator['stack'])

        inclusion_tree_node = OrderedDict([
            ('type', resourceType),
            ('url', resourceUrl),
            ('headers', resourceHeaders),
            ('children', [])
        ])

        if resourceType == 'document':
            inclusion_tree[('document', frameId, loaderId)] = inclusion_tree_node

            if frameId not in frames:
                frames[frameId] = {}

            if initiator_script_id is not None:
                frames[frameId]['initiatorScriptId'] = initiator_script_id

            frames[frameId]['loaderId'] = loaderId
        else:
            if resourceType == 'script':
                inclusion_tree[('script', frameId, resourceUrl)] = inclusion_tree_node

            initiator_script_key = ('script', initiator_script_id)

            if initiator_script_id is not None and initiator_script_key in inclusion_tree:
                inclusion_tree[initiator_script_key]['children'].append(inclusion_tree_node)
            else:
                resource_doc_key = ('document', frameId, loaderId)

                if resource_doc_key in inclusion_tree:
                    inclusion_tree[resource_doc_key]['children'].append(inclusion_tree_node)

        del resource_requests[requestId]

def handle_frame(method, params):
    global root_doc

    if method == 'Page.frameAttached':
        frameId = params['frameId']

        if frameId not in frames:
            frames[frameId] = {}

        if 'stack' in params:
            frames[frameId]['initiatorScriptId'] = get_scriptid_from_stack_trace(params['stack'])
    elif method == 'Page.frameNavigated':
        frameId = params['frame']['id']
        parentFrameId = params['frame']['parentId'] if 'parentId' in params['frame'] else None
        loaderId = params['frame']['loaderId']
        url = params['frame']['url'].strip()

        #if not url.strip().lower().startswith('http:') and not url.strip().lower().startswith('https:'):
        #    return

        if frameId not in frames:
            frames[frameId] = {}

        frames[frameId]['parentId'] = parentFrameId
        frames[frameId]['loaderId'] = loaderId

        frame_key = ('document', frameId, loaderId)

        if frame_key not in inclusion_tree:
            inclusion_tree[frame_key] = OrderedDict([
                ('type', 'document'),
                ('url', url),
                ('headers', None),
                ('children', [])
            ])

            frame_loaders[frameId] = loaderId

        if 'initiatorScriptId' in frames[frameId]:
            inclusion_tree[('script', frames[frameId]['initiatorScriptId'])]['children'].append(inclusion_tree[frame_key])
        elif parentFrameId is not None:
            parent_frame_key = ('document', parentFrameId, frames[parentFrameId]['loaderId'])
            inclusion_tree[parent_frame_key]['children'].append(inclusion_tree[frame_key])
        elif root_doc is None:
            root_doc = frame_key

        if 'executionContextId' in frames[frameId]:
            executionContextId = frames[frameId]['executionContextId']

            alt_frame_key = ('document', frameId, executionContextId)

            if alt_frame_key not in inclusion_tree:
                inclusion_tree[alt_frame_key] = inclusion_tree[frame_key]
    elif method == 'Runtime.executionContextCreated':
        frameId = params['context']['auxData']['frameId']
        executionContextId = params['context']['id']

        if frameId not in frames:
            frames[frameId] = {}

        frames[frameId]['executionContextId'] = executionContextId

        if 'loaderId' in frames[frameId]:
            inclusion_tree[('document', frameId, executionContextId)] = inclusion_tree[('document', frameId, frames[frameId]['loaderId'])]

def handle_script(method, params):
    scriptId = params['scriptId']
    frameId = params['executionContextAuxData']['frameId']
    scriptUrl = params['url'].strip()

    if scriptUrl.lower().startswith('extensions::') or \
       scriptUrl.lower().startswith('chrome-extension://'):
        return

    script_key = ('script', frameId, scriptUrl)

    if script_key in inclusion_tree:
        inclusion_tree[('script', scriptId)] = inclusion_tree[script_key]
        del inclusion_tree[script_key]
    else:
        inclusion_tree[('script', scriptId)] = OrderedDict([
            ('type', 'script'),
            ('url', None),
            ('headers', None),
            ('children', [])
        ])

        if 'stack' in params:
            initiatorScriptId = get_scriptid_from_stack_trace(params['stack'])
            inclusion_tree[('script', initiatorScriptId)]['children'].append(inclusion_tree[('script', scriptId)])
        else:
            if frameId in frames and 'loaderId' in frames[frameId]:
                inclusion_tree[('document', frameId, frames[frameId]['loaderId'])]['children'].append(\
                                        inclusion_tree[('script', scriptId)])

def handle_websocket(method, websocket):
    requestId = websocket['requestId']

    if method == 'Network.webSocketCreated':
        new_node = OrderedDict([
            ('type', 'websocket'),
            ('url', websocket['url'].strip()),
            ('headers', []),
            ('data', []),
            ('closeTimestamp', None)
        ])

        if requestId not in websockets:
            websockets[requestId] = {
                'scriptId': None,
                'wallTime': None,
                'docUrl': None
            }

        if 'initiator' in websocket and \
           'type' in websocket['initiator'] and \
           websocket['initiator']['type'].strip().lower() == 'script' and \
           'stack' in websocket['initiator']:
           websockets[requestId]['scriptId'] = get_scriptid_from_stack_trace(websocket['initiator']['stack'])

        if ('script', websockets[requestId]['scriptId']) in inclusion_tree:
            inclusion_tree[('script', websockets[requestId]['scriptId'])]['children'].append(new_node)
        else:
            inclusion_tree[root_doc]['children'].append(new_node)

        websockets[requestId]['node'] = new_node
    elif method == 'Network.webSocketWillSendHandshakeRequest':
        websockets[requestId]['timestamp'] = websocket['timestamp']
        websockets[requestId]['wallTime'] = websocket['wallTime']
        websockets[requestId]['node']['headers'].append({
            'timestamp': websocket['wallTime'],
            'request': websocket['request']['headers']
        })
    elif method == 'Network.webSocketHandshakeResponseReceived':
        websockets[requestId]['node']['headers'][-1]['response'] = websocket['response']['headers']
        websockets[requestId]['node']['headers'][-1]['status'] = \
                (str(websocket['response']['status']) + ' ' + websocket['response']['statusText']).strip()
    elif method in ['Network.webSocketFrameSent', 'Network.webSocketFrameReceived']:
        websockets[requestId]['node']['data'].append({
            'type': 'send' if method == 'Network.webSocketFrameSent' else 'receive',
            'timestamp': websockets[requestId]['wallTime'] + websocket['timestamp'] - websockets[requestId]['timestamp']
        })

        websockets[requestId]['node']['data'][-1].update(websocket['response'])
    elif method == 'Network.webSocketClosed':
        if websockets[requestId]['wallTime']:
            websockets[requestId]['node']['closeTimestamp'] = websockets[requestId]['wallTime'] + \
                                                              websocket['timestamp'] - \
                                                              websockets[requestId]['timestamp']

def handle_console(method, params):
    if 'args' in params and len(params['args']) > 0 and \
       'type' in params['args'][0] and params['args'][0]['type'].strip().lower() == 'string' and \
       'value' in params['args'][0] and params['args'][0]['value'].strip().lower().startswith('sajjad_'):
        msg_content = params['args'][0]['value'].strip()

        if msg_content.startswith('sajjad_links_') or \
            msg_content.startswith('sajjad_styles_') or \
            msg_content.startswith('sajjad_doctype_'):
            return
        elif msg_content.startswith('sajjad_adblockplus_'):
            message = json.loads(msg_content.replace('sajjad_adblockplus_', ''))

            location = urlparse.urldefrag(message['location'].strip())[0]

            if location not in roles:
                roles[location] = set()

            for l in message['lists']:
                if l.strip().lower() in adblockplus_lists:
                    roles[location].add(adblockplus_lists[l.strip().lower()])
                else:
                    roles[location].add(l)
        else:
            message = json.loads(params['args'][0]['value'].replace('sajjad_', ''))

            message['timestamp'] = params['timestamp'] if 'timestamp' in params else None

            script_id = None
            if 'stackTrace' in params:
                script_id = get_scriptid_from_stack_trace(params['stackTrace'])

            if message['class'] in ['RTCPeerConnection', 'RTCDataChannel']:
                if 'output' in message and type(message['output']) == dict and 'sajjadId' in message['output']:
                    del message['output']['sajjadId']

                api = OrderedDict([
                    ('type', 'webrtc'),
                    ('timestamp', message['timestamp']),
                    ('class', message['class']),
                    ('method', message['method']),
                    ('args', message['args']),
                    ('output', message['output'])
                ])

                if ('script', script_id) in inclusion_tree:
                    inclusion_tree[('script', script_id)]['children'].append(api)

def handle_cookie(method, params):
    if params is not None and 'cookies' in params:
        for coo in params['cookies']:
            cookies.add(json.dumps(coo))

def prune_inclusion_tree(inc_tree):
    if 'children' in inc_tree:
        pos = 0
        while pos < len(inc_tree['children']):
            child = inc_tree['children'][pos]

            prune_inclusion_tree(child)

            if 'children' in child and len(child['children']) == 0 and child['url'] is None:
                del inc_tree['children'][pos]
            else:
                pos += 1

def get_inclusion_tree(raw_logs):
    global frames
    global resource_requests
    global frame_loaders
    global inclusion_tree
    global websockets
    global root_doc
    global roles
    global adblockplus_lists
    global cookies

    logs = json.loads(raw_logs)

    handlers = {
        'Network.webSocketCreated': handle_websocket,
        'Network.webSocketWillSendHandshakeRequest': handle_websocket,
        'Network.webSocketHandshakeResponseReceived': handle_websocket,
        'Network.webSocketFrameSent': handle_websocket,
        'Network.webSocketFrameReceived': handle_websocket,
        'Network.webSocketClosed': handle_websocket,

        'Network.requestWillBeSent': handle_request_response,
        'Network.responseReceived': handle_request_response,

        'Page.frameNavigated': handle_frame,
        'Page.frameAttached': handle_frame,
        'Runtime.executionContextCreated': handle_frame,

        'Debugger.scriptParsed': handle_script,

        'Runtime.consoleAPICalled': handle_console,

        'Network.getAllCookies': handle_cookie
    }

    website_inclusion_tree = OrderedDict([('site', logs['site']), ('urls', [])])

    for page in logs['pages']:
        resource_requests = {}
        frame_loaders = {}
        inclusion_tree = {}
        frames = {}
        websockets = {}
        root_doc = None

        for event in page['events']:
            try:
                if event['method'] in handlers:
                    handlers[event['method']](event['method'], event['params'])
            except:
                print >> sys.stderr, traceback.format_exc(), page['url'], event

        if root_doc is not None:
            try:
                if inclusion_tree[root_doc]['url'].strip().startswith('http'):
                    json.dumps(inclusion_tree[root_doc])
                    prune_inclusion_tree(inclusion_tree[root_doc])
                    website_inclusion_tree['urls'].append(inclusion_tree[root_doc])
            except:
                print >> sys.stderr, traceback.format_exc()

    return website_inclusion_tree

if __name__ == '__main__':
    try:
        website_inclusion_tree = get_inclusion_tree(open(sys.argv[1], 'r').read())
        print json.dumps(website_inclusion_tree)
    except:
        print >> sys.stderr, traceback.format_exc()

