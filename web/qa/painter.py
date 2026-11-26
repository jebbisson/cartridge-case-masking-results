"""Exercise unsaved painter edits in Chromium on the local workbench.

Run via browser_exec: run_path('/.../web/qa/painter.py')['check_painter'](
    new_tab, wait_for_load, cdp, js)
"""
import time


def check_painter(new_tab, wait_for_load, cdp, js, url='http://127.0.0.1:8787/', part=None):
    new_tab(url)
    cdp('Page.bringToFront')
    cdp('Network.setCacheDisabled', cacheDisabled=True)
    cdp('Page.reload', ignoreCache=True)
    cdp('Emulation.setDeviceMetricsOverride', width=1536, height=980,
        deviceScaleFactor=1, mobile=False)
    def loaded():
        wait_for_load()
        for _ in range(100):
            if js("!!document.querySelector('button[title=Brush]:enabled')"):
                return
            time.sleep(.1)
        raise AssertionError('No editable scan loaded')

    loaded()

    def click(selector):
        js(f'document.querySelector({selector!r}).click()')

    def brush_size(value):
        js(f'''(() => {{const s = document.querySelector('.brush-control select');
          s.value = {value}; s.dispatchEvent(new Event('change', {{bubbles: true}}));}})()''')

    def at(x, y):
        return js(f'''(() => {{const s=document.querySelector('.scan-sheet');
          const r=s.getBoundingClientRect(), im=s.querySelector('img');
          return [r.left + ({x}+.5)*r.width/im.naturalWidth, r.top + ({y}+.5)*r.height/im.naturalHeight];}})()''')

    def move(xy, down=False):
        cdp('Input.dispatchMouseEvent', type='mouseMoved', x=xy[0], y=xy[1], button='left' if down else 'none', buttons=int(down))
        js('new Promise(requestAnimationFrame)')

    def stroke(a, b):
        press(a)
        release(b)

    def press(a):
        a = at(*a)
        move(a)
        cdp('Input.dispatchMouseEvent', type='mousePressed', x=a[0], y=a[1], button='left', buttons=1, clickCount=1)

    def release(b):
        b = at(*b)
        move(b, True)
        cdp('Input.dispatchMouseEvent', type='mouseReleased', x=b[0], y=b[1], button='left', buttons=0, clickCount=1)

    def status(value=None, focus=False):
        return js(f'''(() => {{const s=document.querySelector('[aria-label="Breech face status"]');
          {'s.focus();' if focus else ''}
          {f"s.value = '{value}'; s.dispatchEvent(new Event('change', {{bubbles: true}}));" if value else ''}
          return s.value;}})()''')

    def undo(modifiers=2):
        for kind in ('keyDown', 'keyUp'):
            cdp('Input.dispatchKeyEvent', type=kind, key='z', code='KeyZ', modifiers=modifiers, windowsVirtualKeyCode=90)
        js('new Promise(requestAnimationFrame)')

    def pixels(layer=0):
        return js(f'''(() => {{const ctx=document.querySelectorAll('.scan-sheet canvas')[{layer}].getContext('2d');
          return [[80,80],[160,80],[240,80]].map(([x,y])=>ctx.getImageData(x,y,1,1).data[3]);}})()''')

    click('button[title=Brush]')
    brush_size(41)
    if part == 'enter':
        move([20, 20])
        initial = pixels()
        x, y = at(80, 80)
        js(f'''document.querySelector('.scan-sheet img').dispatchEvent(new PointerEvent('pointerover', {{
            bubbles:true, pointerType:'mouse', isPrimary:true, clientX:{x}, clientY:{y}, buttons:0
        }}))''')
        assert js("!!document.querySelector('.brush-stamp')"), 'Pointer entry without a move or click did not show the brush footprint'
        assert pixels() == initial, 'Pointer entry must not paint'
        assert 'Unsaved edits' not in js("document.querySelector('.review-state').innerText")
        return

    if part == 'cursor-fallback':
        move([20, 20])
        cursor = js("getComputedStyle(document.querySelector('.scan-sheet img')).cursor")
        assert cursor.startswith('url(') and '235%2C65%2C67' in cursor, cursor
        click('button[title=Pan]')
        assert js("getComputedStyle(document.querySelector('.scan-sheet img')).cursor") == 'grab'
        return

    if part == 'reload':
        initial = pixels()
        state = js("document.querySelector('.review-state').innerText")
        js('window.reloadProbe = true')
        stroke((80, 80), (160, 80))
        assert pixels() != initial
        assert 'Unsaved edits' in js("document.querySelector('.review-state').innerText")
        # Send the reload without waiting on the browser's unsaved-edits dialog.
        js('setTimeout(() => location.reload(), 0); true')
        time.sleep(.3)
        try:
            cdp('Page.handleJavaScriptDialog', accept=True)
        except Exception as exc:
            if 'dialog' not in str(exc).lower():
                raise
        loaded()
        assert not js('window.reloadProbe === true'), 'Page did not actually reload'
        assert pixels() == initial, 'Unsaved stroke survived an actual reload'
        assert js("document.querySelector('.review-state').innerText") == state
        assert js("document.querySelector('.undo-stroke').disabled")
        print('Actual reload restored the saved revision and discarded the unsaved stroke.')
        return

    if part in ('status', 'late-status'):
        stroke((80, 80), (80, 80))
        if part == 'status':
            status('indeterminate', focus=True)
            undo()
            assert pixels() == [0, 0, 0], 'Focused dropdown blocked stroke undo'
            assert status() == 'indeterminate', 'Stroke undo reverted an independent status edit'
        else:
            status('absent')
            press((80, 80))  # Starts entirely over already painted pixels.
            status('indeterminate')
            release((160, 80))
            assert status() == 'present' and pixels() == [100, 100, 0]
            undo()
            assert status() == 'indeterminate', 'Undo did not restore the status before the first changed pixel'
            assert pixels() == [100, 0, 0]
        return

    if part == 'zoom-glyph':
        for _ in range(20):
            if js('document.querySelector(\'[aria-label="Zoom in"]\').disabled'):
                break
            click('[aria-label="Zoom in"]')
        pos = js('''(async () => {
          const v=document.querySelector('.scan-viewport');
          v.scrollLeft = 1200; v.scrollTop = 1600;
          await new Promise(requestAnimationFrame);
          const r=v.getBoundingClientRect();
          return [r.left+v.clientWidth-42, r.top+v.clientHeight/2];
        })()''')
        move(pos)
        assert js('''(() => {
          const v=document.querySelector('.scan-viewport'), b=v.getBoundingClientRect();
          const glyph=document.querySelector('.brush-glyph')?.getBoundingClientRect();
          return glyph && glyph.width > 0 && glyph.left >= b.left && glyph.right <= b.left+v.clientWidth &&
              glyph.top >= b.top && glyph.bottom <= b.top+v.clientHeight;
        })()'''), 'Brush glyph was clipped at high zoom'
        return

    if part != 'cursor':
        base = pixels()
        assert base == [0, 0, 0], base
        stroke((80, 80), (160, 80))
        stroke((240, 80), (240, 80))
        assert pixels() == [100, 100, 100], pixels()
        click('button[title=Eraser]')
        stroke((160, 80), (240, 80))
        assert pixels() == [100, 0, 0], pixels()
        undo()
        assert pixels() == [100, 100, 100], 'Ctrl+Z did not restore the erased pixels'
        undo()
        assert pixels() == [100, 100, 0], 'Ctrl+Z did not remove just the newest paint stroke'
        undo(4)
        assert pixels() == base, 'Cmd+Z did not remove the full drag as one stroke'
        assert 'Unsaved edits' not in js("document.querySelector('.review-state').innerText")
        assert js("document.querySelector('.undo-stroke').disabled")
        print('Undo: eraser pixels restored, individual strokes undone, and clean state recovered.')

    if part != 'undo':
        click('button[title=Brush]')
        move(at(160, 160))
        assert js("getComputedStyle(document.querySelector('.scan-sheet img')).cursor") == 'none', 'Brush mode still shows the native cursor'

        def preview():
            return js('''(() => {const p = document.querySelector('.brush-preview');
              const svg = p?.querySelector('svg.brush-stamp');
              const r = svg?.getBoundingClientRect();
              return svg && r.width > 0 ? [getComputedStyle(p).color, r.width, r.left+r.width/2, r.top+r.height/2] : null;})()''')

        p = preview()
        assert p and p[0] == 'rgb(235, 65, 67)', p
        x, y = at(160, 160)
        assert abs(p[2]-x) < .5 and abs(p[3]-y) < .5, (p, x, y)
        click('.layer-pick[aria-pressed=false]:has(+ [aria-label="Firing pin shear overlay"])')
        assert preview()[0] == 'rgb(171, 101, 217)', preview()
        brush_size(9)
        assert abs(preview()[1] / p[1] - 9/41) < .02, (p, preview())
        assert pixels() == [0, 0, 0], 'Hover must never modify the mask'
        for selector in ('button[title=Eraser]', 'button[title=Arrow]', 'button[title=Pan]', 'button[title=Brush]', '.original-toggle'):
            click(selector)
            if selector != 'button[title=Brush]':
                assert not preview(), selector
                assert js("!['none','crosshair'].includes(getComputedStyle(document.querySelector('.scan-sheet img')).cursor)"), selector
        click('.original-toggle')
        move(at(160, 160))
        assert preview(), 'Brush preview did not return from original-only view'
        move([20, 20])
        assert not preview(), 'Brush preview remained outside the scan'
        print('Cursor: colored preview follows the native pixel, updates with size/layer, and appears only on-scan in Brush mode.')
