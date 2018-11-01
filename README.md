# Introduction

A website can include resources in an HTML document from any origin so long as the inclusion respects the same origin policy, its standard exceptions, or any additional policies due to the use of `CSP`, `CORS`, or other access control framework. A first approximation to understanding the inclusions of third-party content for a given web page is to process its `DOM tree` while the page loads. However, direct use of a web page's DOM tree is unsatisfactory because the DOM does not in fact reliably record the inclusion relationships between resources referenced by a page. This follows from the ability for JavaScript to manipulate the DOM at run-time using the DOM API.

Instead, in this work we define an `Inclusion Tree` abstraction extracted directly from the browser's resource loading code. Unlike a DOM tree, the inclusion tree represents how different resources are included in a web page that is invariant with respect to run-time DOM updates. It also discards irrelevant portions of the DOM tree that do not reference remote content. For each resource in the inclusion tree, there is an `Inclusion Sequence (Chain)` that begins with the root resource (i.e., the URL of the web page) and terminates with the corresponding resource. Furthermore, browser extensions can also manipulate the web page by injecting and executing JavaScript code in the page's context. Hence, the injected JavaScript is considered a direct child of the root node in the inclusion tree. An example of a DOM tree and its corresponding inclusion tree is shown in Figure~\ref{inclusion:fig:dom_inclusion_tree}. As shown in Figure~\ref{inclusion:fig:dom_inclusion_tree}b, `f.org/flash.swf` has been dynamically added by an `inline script` to the DOM tree, and its corresponding `inclusion sequence (chain)` has a length of 4 since we remove the `inline` resources from inclusion sequence (chain). Moreover, `ext-id/script.js` is injected by an extension as the direct child of the root resource. This script then included `g.com/script.js`, which in turn included `h.org/img.jpg`.

# Prerequisites

Install `NodeJS` from https://nodejs.org/en/download/. Then, run the following command to install the dependencies:

``` sh
npm install chrome-launcher chrome-remote-interface url-parse util tldjs path shuffle-array argparse
```

# Crawling

``` sh
node crawler.js --site DOMAIN --number NUM_URLS [--cookies FILENAME] [--headless] > output.logs
```

The cookie filename is an optional JSON file, which can be extracted from `output.logs`.

# Inclusion Tree

``` sh
./inclusion_tree.py output.logs > output.json
```

# Reference

[1] **Sajjad Arshad**, Amin Kharraz, William Robertson, "**Include Me Out: In-Browser Detection of Malicious Third-Party Content Inclusions**",  International Conference on Financial Cryptography and Data Security (**FC**), **2016**.
