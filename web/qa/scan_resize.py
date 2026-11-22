"""Browser regression for the workbench viewer. Run via browser_exec:

    run_path('/absolute/path/to/web/qa/scan_resize.py')['check_scan_resize'](
        new_tab, wait_for_load, cdp, js)
"""

import time


def check_scan_resize(new_tab, wait_for_load, cdp, js, url='http://127.0.0.1:8787/'):
    def resize(width, height):
        cdp('Emulation.setDeviceMetricsOverride', width=width, height=height,
            deviceScaleFactor=1, mobile=False)

    new_tab(url)
    cdp('Page.bringToFront')
    cdp('Network.setCacheDisabled', cacheDisabled=True)
    cdp('Page.reload', ignoreCache=True)
    resize(1536, 980)
    wait_for_load()
    for _ in range(80):
        if js('!!document.querySelector(".scan-sheet img")?.naturalWidth'):
            break
        time.sleep(0.1)
    else:
        raise AssertionError('No scan loaded')
    js('new Promise(requestAnimationFrame)')

    # With classic scrollbars, shrinking previously made the old scan-space
    # dimensions overflow and the fit briefly shrank by another 15 px.
    sizes = [(1280, 800), (1250, 800), (1178, 800), (940, 740), (761, 680),
             (760, 680), (1312, 781), (1475, 770), (1517, 791), (1518, 792), (1517, 793)]
    failures = []
    for width, height in sizes:
        resize(width, height)
        failure = js('''(async () => {
          const v = document.querySelector('.scan-viewport');
          const s = document.querySelector('.scan-sheet');
          const img = s.querySelector('img');
          for (let i = 0; i < 8; i++) {
            await new Promise(requestAnimationFrame);
            const r = s.getBoundingClientRect(), b = v.getBoundingClientRect();
            const iw = img.naturalWidth, ih = img.naturalHeight;
            const fit = Math.min(1, (b.width - 40) / iw, (b.height - 40) / ih);
            const dx = r.left + r.width / 2 - (b.left + b.width / 2);
            const dy = r.top + r.height / 2 - (b.top + b.height / 2);
            const bars = [v.offsetWidth - v.clientWidth, v.offsetHeight - v.clientHeight];
            if (bars.some(Boolean) || Math.abs(r.width - fit * iw) > .75 ||
                Math.abs(r.height - fit * ih) > .75 || Math.abs(dx) > .75 || Math.abs(dy) > .75) {
              return { frame: i, bars, fitWidth: fit * iw, actualWidth: r.width, dx, dy };
            }
          }
          return null;
        })()''')
        if failure:
            failures.append(((width, height), failure))
    assert not failures, f'{len(failures)} unstable sizes; first: {failures[:3]}'

    js('document.querySelector(\'[aria-label="Set zoom to 100 percent"]\').click()')
    resize(1070, 720)
    manual = js('''(async () => {
      await new Promise(requestAnimationFrame);
      const v = document.querySelector('.scan-viewport');
      const s = document.querySelector('.scan-sheet');
      const img = s.querySelector('img');
      v.scrollTop = 45; v.scrollLeft = 45;
      return [s.offsetWidth === img.naturalWidth, s.offsetHeight === img.naturalHeight,
              v.scrollTop === 45, v.scrollLeft === 45];
    })()''')
    assert all(manual), manual
    js('document.querySelector(\'[aria-label="Fit scan to view"]\').click()')
    fit_again = js('''(async () => {
      await new Promise(requestAnimationFrame);
      const v = document.querySelector('.scan-viewport');
      const s = document.querySelector('.scan-sheet');
      return [v.scrollLeft, v.scrollTop, s.offsetWidth < s.querySelector('img').naturalWidth];
    })()''')
    assert fit_again == [0, 0, True], fit_again
    print(f'Fit stable across all {len(sizes)} sizes; manual zoom scrolls and returns to fit.')
