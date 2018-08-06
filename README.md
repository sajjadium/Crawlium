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
