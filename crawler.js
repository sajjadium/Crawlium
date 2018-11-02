const ChromeRemoteInterface = require('chrome-remote-interface');
const ChromeLauncher = require('chrome-launcher');
const UrlParse = require('url-parse');
const Util = require('util');
const Path = require('path');
const TLDJS = require('tldjs');
const ShuffleArray = require('shuffle-array');
const FS = require('fs');
const ArgParse = require('argparse');

let SITE = null;
let COUNT = 0;
let LANDING_DOMAIN = null;
let COOKIE_FILENAME = null;
let HEADLESS = false;
let OUTPUT_LOGS_FILENAME = null;
let OUTPUT_COOKIE_FILENAME = null;

function parseArguments() {
    let parser = new ArgParse.ArgumentParser({
      version: '0.0.1',
      addHelp:true,
      description: 'Argparse example'
    });

    parser.addArgument(
      '--site',
      {
        action: 'store',
        required: true,
        help: 'Domain (e.g., google.com)'
      }
    );
    parser.addArgument(
      '--count',
      {
        action: 'store',
        type: 'int',
        required: true,
        help: 'Number of URLs'
      }
    );
    parser.addArgument(
      '--load-cookies',
      {
        action: 'store',
        defaultValue: null,
        help: 'A JSON file that contains cookies'
      }
    );
    parser.addArgument(
      '--headless',
      {
        action: 'storeTrue',
        defaultValue: false,
        help: 'Using headless mode in servers'
      }
    );
    parser.addArgument(
      '--output-cookies',
      {
        action: 'store',
        defaultValue: null,
        help: 'A JSON file that will contain the output cookies'
      }
    );
    parser.addArgument(
      '--output-logs',
      {
        action: 'store',
        defaultValue: null,
        help: 'A JSON file that will contain the output logs'
      }
    );

    let args = parser.parseArgs();

    SITE = args.site;
    COUNT = args.count;
    LANDING_DOMAIN = SITE;
    HEADLESS = args.headless;
    COOKIE_FILENAME = args.load_cookies;
    OUTPUT_COOKIE_FILENAME = args.output_cookies;
    OUTPUT_LOGS_FILENAME = args.output_logs;
}

const DOMAINS = [
    'Inspector',
    'Page',
    'Security',
    'Network',
    'Database',
    'IndexedDB',
    'DOMStorage',
    'ApplicationCache',
    'DOM',
    'CSS',
    'ServiceWorker',
    'Log',
    'Runtime',
    'Debugger',
    'Console'
];

const EXCLUDED_EXTENSIONS = [
    '.zip',
    '.exe',
    '.dmg',
    '.doc',
    '.docx',
    '.odt',
    '.pdf',
    '.rtf',
    '.tex',
    '.mp3',
    '.ogg',
    '.wav',
    '.wma',
    '.7z',
    '.rpm',
    '.gz',
    '.tar',
    '.deb',
    '.iso',
    '.sql',
    '.apk',
    '.jar',
    '.bmp',
    '.gif',
    '.jpg',
    '.jpeg',
    '.png',
    '.ps',
    '.tif',
    '.tiff',
    '.ppt',
    '.pptx',
    '.xls',
    '.xlsx',
    '.dll',
    '.msi'
];

function Browser() {
}

function BrowserTab(port) {
    this.port = port;
    this.events = [];
}

BrowserTab.prototype.connect = async function() {
    this.tab = await ChromeRemoteInterface.New({port: this.port});
    this.client = await ChromeRemoteInterface({target: this.tab.webSocketDebuggerUrl});

    for (let domain of DOMAINS) {
        try {
            await this.client.send(Util.format("%s.enable", domain), {});
        } catch (ex) {
            console.error(domain, ex.message, ex.stack);
        }
    }

    await this.client.Page.addScriptToEvaluateOnNewDocument({
        source: 'window.alert = function() {}; \
                 window.confirm = function() {}; \
                 window.prompt = function() {};'
    });

    await this.client.Network.setCacheDisabled({
        cacheDisabled: true
    });
}

BrowserTab.prototype.close = async function(timeout=10) {
    let that = this;

    return new Promise(resolve => {
        try {
            that.client.removeAllListeners('event');
            that.client.removeAllListeners('Page.loadEventFired');

            that.client.close(function() {
                ChromeRemoteInterface.Close({
                    port: that.port,
                    id: that.tab.id
                }, function() {
                    resolve();
                });
            });

            setTimeout(resolve, timeout * 1000);
        } catch (ex) {
            console.error(ex.message, ex.stack);
            resolve();
        }
    });
}

BrowserTab.prototype.goto = async function(url, timeout=10) {
    let that = this;

    return new Promise(resolve => {
        try {
            that.client.on('event', function(message) {
                that.events.push(message);
            });

            that.client.Page.loadEventFired(function() {
                resolve();
            });

            that.client.Page.navigate({url: url});

            setTimeout(resolve, timeout * 1000);
        } catch (ex) {
            console.error(ex.message, ex.stack);
            resolve();
        }
    });
}

BrowserTab.prototype.evaluateScript = async function(script, timeout=10) {
    let that = this;

    return new Promise(resolve => {
        try {
            that.client.Runtime.evaluate({
                expression: script,
                returnByValue: true
            }).then(result => {
                resolve(result.result.value);
            }).catch(err => {
                console.error(err);
                resolve(null);
            });

            setTimeout(function() {
                resolve(null);
            }, timeout * 1000);
        } catch (ex) {
            console.error(ex.message, ex.stack);
            resolve(null);
        }
    });
}

Browser.prototype.close = async function() {
    try {
        await this.browser.kill();
    } catch (ex) {
        console.error(ex.message, ex.stack);
    }
}

Browser.prototype.launch = async function() {
    flags = [
        '--disable-gpu',
        '--no-sandbox',
        '--start-maximized',
        '--ignore-certificate-errors',
        '--password-store=basic'
    ];

    if (HEADLESS)
        flags.push('--headless');

    this.browser = await ChromeLauncher.launch({
        chromeFlags: flags
    });

    await sleep(10);
}

Browser.prototype.openTab = async function() {
    let browser_tab = new BrowserTab(this.browser.port);
    await browser_tab.connect();
    return browser_tab;
}

module.exports = Browser;
module.exports = BrowserTab;

(async () => {
    parseArguments();

    let result = {
        site: SITE,
        cookies: [],
        pages: []
    };

    let cookies = [];

    if (COOKIE_FILENAME != null) {
        cookies = JSON.parse(FS.readFileSync(COOKIE_FILENAME, 'utf8'));
    }

    let browser = new Browser();

    await browser.launch();

    let cookie_tab = await browser.openTab();

    for (let cookie of cookies) {
        try {
            await cookie_tab.client.Network.setCookie(cookie);
        } catch (ex) {
            console.error(ex.message, ex.stack);
        }
    }

    await cookie_tab.close();

    let visited_urls = new Set();
    let url_queue = [Util.format('http://%s/', SITE)];

    while (url_queue.length > 0 && visited_urls.size < COUNT) {
        try {
            ShuffleArray(url_queue);

            let url = url_queue.shift().trim();

            if (visited_urls.has(url.toLowerCase()))
                continue;

            let browser_tab = await browser.openTab();

            await browser_tab.goto(url, 10);

            await browser_tab.evaluateScript('window.scrollTo(0, document.body.scrollHeight);');

            await sleep(10);

            if (url === Util.format('http://%s/', SITE)) {
                try {
                    let landing_url = JSON.parse(await browser_tab.evaluateScript('JSON.stringify(document.URL);'));
                    let landing_domain = TLDJS.parse(landing_url).domain;

                    if (landing_domain) {
                        LANDING_DOMAIN = landing_domain;
                    }
                } catch (ex) {
                    console.error(ex.message, ex.stack);
                }
            }

            let links = await extractLinks(browser_tab);

            for (let l of links)
                url_queue.push(l);

            visited_urls.add(url.toLowerCase());

            try {
                let cookies = await browser_tab.client.Network.getAllCookies();

                if (cookies !== null)
                    result.cookies = cookies.cookies;
            } catch (ex) {
                console.error(ex.message, ex.stack);
            }

            await browser_tab.close();

            result.pages.push({
                url: url,
                events: browser_tab.events
            });
        } catch (ex) {
            console.error(ex.message, ex.stack);
        }
    }

    FS.writeFileSync(OUTPUT_LOGS_FILENAME, JSON.stringify(result.pages));
    FS.writeFileSync(OUTPUT_COOKIE_FILENAME, JSON.stringify(result.cookies));

    await browser.close();
})();

async function sleep(seconds) {
    return new Promise((resolve) => setTimeout(resolve, seconds * 1000));
}

async function extractLinks(browser_tab) {
    let urls = new Set();

    try {
        let links = await browser_tab.evaluateScript(
            "link_urls = []; \
            links = document.getElementsByTagName('a'); \
            for (let i = 0; i < links.length; i++) { \
                link_urls.push(links[i].href); \
            } \
            JSON.stringify(link_urls);"
        );

        if (links !== null) {
            for (let url of JSON.parse(links)) {
                try {
                    if (isInternalDomain(url)) {
                        let parsed_url = UrlParse(url);

                        if (EXCLUDED_EXTENSIONS.includes(Path.extname(parsed_url.pathname.trim().toLowerCase())))
                            continue;

                        parsed_url.hash = '';

                        urls.add(parsed_url.toString().trim());
                    }
                } catch (ex) {
                    console.error(ex.message, ex.stack);
                }
            }
        }
    } catch (ex) {
        console.error(ex.message, ex.stack);
    }

    return urls;
}

function isInternalDomain(url) {
    let parsed_url = UrlParse(url);

    if (!["http:", "https:"].includes(parsed_url.protocol.toLowerCase().trim()))
        return false;

    if (parsed_url.hostname) {
        url_domain = parsed_url.hostname.trim().toLowerCase();

        if (url_domain === SITE || url_domain.endsWith('.' + SITE))
            return true;

        if (url_domain === LANDING_DOMAIN || url_domain.endsWith('.' + LANDING_DOMAIN))
            return true;
    }

    return false;
}
