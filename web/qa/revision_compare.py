"""Browser acceptance: compare saved overlays without losing unsaved edits."""
import time


def check_compare(new_tab, wait_for_load, js, url):
    new_tab(url)
    wait_for_load()

    def wait(expr):
        for _ in range(100):
            if value := js(expr):
                return value
            time.sleep(.1)
        raise AssertionError(expr)

    def button(name):
        return f"[...document.querySelectorAll('button')].find(b=>b.innerText.trim()==={name!r})"

    def case(prefix):
        return f"[...document.querySelectorAll('.case-row')].find(b=>b.textContent.startsWith({prefix!r}))"

    def revision(number):
        return f"[...document.querySelectorAll('.revision-row')].find(b=>b.querySelector('.revision-code')?.textContent==='r{number}')"

    def click(expr):
        assert js(f"(()=>{{const b={expr}; if(!b||b.disabled)return false; b.click(); return true;}})()"), expr

    cur = "document.querySelector('.case-revision')?.textContent"
    state = "document.querySelector('.review-state')?.innerText"
    red = "document.querySelector('[aria-label=\"Breech face status\"]')"
    pixel = "document.querySelector('.scan-sheet canvas')?.getContext('2d').getImageData(1500,1050,1,1).data[3]"
    click_when = lambda expr: (wait(f'!!({expr})'), click(expr))
    click_when(case('BWC506US RP1'))
    wait(f"{cur}==='r163' && !{red}.disabled && {pixel}<35")
    js('window.qaPrompts=[]; window.qaDiscard=false; window.confirm=message=>{window.qaPrompts.push(message);return window.qaDiscard}')
    click(button('Pan'))
    click("document.querySelector('[aria-label=\"Set zoom to 100 percent\"]')")
    zoom = "document.querySelector('.zoom-value').textContent"
    assert js(zoom) == '100%'
    js(f"(()=>{{const s={red};s.value='indeterminate';s.dispatchEvent(new Event('change',{{bubbles:true}}));}})()")
    wait(f"{state}==='Unsaved edits' && {red}.value==='indeterminate'")
    click(revision(103))
    assert js('window.qaPrompts.length') == 0, 'Opening a revision asked to discard unsaved edits'
    wait(f"{cur}==='r103' && {red}.disabled && {pixel}>35")
    assert js(zoom) == '100%'
    assert js(f'{button("Save draft")}.disabled && {button("Approve")}.disabled')
    click(revision(163))
    wait(f"{cur}==='r163' && {red}.disabled && {red}.value==='present' && {pixel}<35")
    click(button('Back to unsaved edits'))
    wait(f"{state}==='Unsaved edits' && !{red}.disabled && {red}.value==='indeterminate'")
    assert js(zoom) == '100%'
    click(revision(103))
    wait(f"{cur}==='r103' && {pixel}>35")
    click(case('CWS111US RP2'))
    assert js('window.qaPrompts.length') == 1
    assert js(cur) == 'r103', 'Declining case navigation changed the revision'
    click(button('Back to unsaved edits'))
    wait(f"{state}==='Unsaved edits' && {red}.value==='indeterminate'")
    cancel = button('Cancel edits')
    assert js(f"{cancel}.nextElementSibling.textContent.trim()==='Save draft'")
    click(cancel)
    assert js('window.qaPrompts.length') == 2
    assert js(f"{red}.value==='indeterminate'")
    js('window.qaDiscard=true')
    click(cancel)
    wait(f"{cur}==='r163' && !{red}.disabled && {red}.value==='present' && {state}.startsWith('Latest')")
    assert js(f'{cancel}.disabled')
    js(f"(()=>{{const s={red};s.value='indeterminate';s.dispatchEvent(new Event('change',{{bubbles:true}}));}})()")
    wait(f"{state}==='Unsaved edits'")
    click(revision(103)); wait(f"{cur}==='r103'")
    click(case('CWS111US RP2')); wait(f"{cur}==='r166' && !{red}.disabled")
    assert js('window.qaPrompts.length') == 4
    click(case('BWC506US RP1'))
    wait(f"{cur}==='r163' && !{red}.disabled && {red}.value==='present' && {state}.startsWith('Latest')")
    print('Comparison kept unsaved edits and zoom; case change prompted; Cancel edits reset without saving.')
