"""Check workbench refresh and a normal browser reload with caching enabled.

Run check_refresh via browser_exec against a copy of the real pilot database.
"""
import json
import time
from urllib.request import Request, urlopen


def check_refresh(new_tab, wait_for_load, cdp, js, url, latest=133, part='workbench', disposable=False):
    new_tab(url)
    wait_for_load()
    cdp('Network.enable')
    cdp('Network.setCacheDisabled', cacheDisabled=False)

    def view():
        return js('''(() => {
          const c = document.querySelector('.scan-sheet canvas');
          return {title: document.querySelector('h1')?.parentElement?.parentElement?.textContent || '',
            red: c ? [[1500, 1050], [1260, 550]].map(([x, y]) => c.getContext('2d').getImageData(x, y, 1, 1).data[3]) : null};
        })()''')

    def wait_for(probe, predicate, error):
        state = probe()
        for _ in range(50):
            if predicate(state):
                return state
            time.sleep(.1)
            state = probe()
        raise AssertionError(f'{error}; got {state}')

    def expect(revision, alpha):
        wait_for(view, lambda v: v['title'].endswith(f'r{revision}') and v['red'] == [alpha, 100],
                 f'Expected r{revision} and rendered red alpha {[alpha, 100]}')

    refresh = "document.querySelector('button[aria-label^=\"Refresh cases\"]')"
    status = "document.querySelector('[aria-label=\"Breech face status\"]')"
    review_state = "document.querySelector('.review-state').innerText"

    expect(latest, 0)
    if part != 'dirty':
        js('''[...document.querySelectorAll('button')]
            .find(button => button.textContent.startsWith('r103Proposal')).click()''')
        expect(103, 100)
    js('window.qaSameDocument = true')
    if part == 'browser':
        cdp('Page.reload', ignoreCache=False)
        wait_for_load()
        expect(latest, 0)
        assert not js('window.qaSameDocument === true'), 'The browser did not reload the document'
    elif part == 'workbench':
        js(f'{refresh}.click()')
        expect(latest, 0)
        assert js('window.qaSameDocument === true'), 'Workbench refresh should not reload the document'
    elif part == 'dirty':
        from urllib.parse import urlsplit
        origin = urlsplit(url)
        if not disposable or (origin.scheme, origin.hostname, origin.port) != ('http', '127.0.0.1', 8791):
            raise ValueError('Dirty test writes only to the disposable loopback QA app on port 8791')
        wait_for(lambda: js(f'!{status}.disabled'), bool, 'Editor did not finish loading')
        js(f'''(() => {{const s = {status}; s.value = 'indeterminate';
            s.dispatchEvent(new Event('change', {{bubbles: true}}));}})()''')
        assert js(review_state) == 'Unsaved edits'
        js(f'setTimeout(() => {refresh}.click(), 0); true')
        time.sleep(.2)
        cdp('Page.handleJavaScriptDialog', accept=False)
        assert js(review_state) == 'Unsaved edits' and js(f'{status}.value') == 'indeterminate'

        case_url = url.rstrip('/') + '/api/cases/edbf0ae9-6615-4bb2-9931-3cea95423f79'
        with urlopen(case_url, timeout=5) as response:
            case = json.load(response)
        assert case['split'] == 'train'

        def include(value):
            req = Request(case_url + '/inclusion', json.dumps({'included': value}).encode(),
                          {'Content-Type': 'application/json'}, method='POST')
            with urlopen(req, timeout=5) as response:
                assert json.load(response)['included'] == value

        excluded = '''[...document.querySelectorAll('.case-row')]
            .find(b => b.innerText.startsWith('DW621US RP1_BFR.png')).innerText.includes('Excluded')'''
        assert js(excluded) == (not case['included'])
        try:
            include(not case['included'])
            assert js(excluded) == (not case['included']), 'Queue unexpectedly updated before refresh'
            # Hold the real list response after the detail and its assets are ready.
            js('''(() => {const original = window.fetch;
                window.fetch = async (path, ...args) => {
                  const response = await original(path, ...args);
                  if (path === '/api/cases') await new Promise(resolve => { window.qaReleaseQueue = resolve; });
                  return response;
                };})()''')
            js(f'setTimeout(() => {refresh}.click(), 0); true')
            time.sleep(.2)
            cdp('Page.handleJavaScriptDialog', accept=True)
            wait_for(lambda: js('typeof window.qaReleaseQueue === "function"'), bool, 'Queue request was not made')
            expect(latest, 0)
            assert js(f'{status}.disabled && document.querySelector(".inclusion-control input").disabled'), \
                'Editor unlocked while a stale queue response could still arrive'
            js('window.qaReleaseQueue(); true')
            wait_for(lambda: js(excluded), lambda v: v == case['included'], 'Queue did not reflect changed inclusion')
            wait_for(lambda: js(f'!{status}.disabled'), bool, 'Editor did not unlock after refresh')
            assert js(f'{status}.value') == 'present' and js(review_state) != 'Unsaved edits'
        finally:
            js('window.qaReleaseQueue?.(); true')
            include(case['included'])
    else:
        raise ValueError(part)
    print(f'{part}: displayed r{latest}, showing the real new red overlay (persistent cache enabled)')
