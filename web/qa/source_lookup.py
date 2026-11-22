"""Check Add scan group lookup without uploading anything."""
import json
import time


def check_source_lookup(new_tab, wait_for_load, js, url='http://127.0.0.1:8787/'):
    new_tab(url)
    wait_for_load()
    for _ in range(100):
        if js("!!document.querySelector('.case-row') && !document.querySelector('.masthead-end button').disabled"):
            break
        time.sleep(.1)
    else:
        raise AssertionError('Workbench did not load its case list')
    js("document.querySelector('.masthead-end button').click()")

    def fill(selector, value):
        js('''(() => {const input = document.querySelector(''' + json.dumps(selector) + ''');
          if (!input) return;
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input, ''' + json.dumps(value) + ''');
          input.dispatchEvent(new Event('input',{bubbles:true}));})()''')

    search = '#source-group-search'
    scan_name = 'dialog [name=name]'
    group = 'dialog [name=group_id]'
    group_value = f"document.querySelector('{group}')?.value || ''"
    fill(search, 'f')
    assert not js("document.querySelector('.source-match')")
    fill(search, '2f27')
    matches = js("Array.from(document.querySelectorAll('.source-match'), row => row.innerText)")
    assert len(matches) == 1 and all(s in matches[0] for s in ('BWC506US RP1', 'BWC506US RP2', 'Train')), matches
    assert js(group_value) == '', 'Typing must not silently assign a group'
    js("document.querySelector('.source-match button').click()")
    assert js(group_value) == '2f27f08f-95fc-4297-a454-5e3cc0722b73'
    assert js(f"document.querySelector('{group}').readOnly")
    selected = js("document.querySelector('.source-selected')?.innerText")
    assert all(s in selected for s in ('Source group selected', 'BWC506US RP1', 'BWC506US RP2', 'Train'))
    assert js(f"document.querySelector('{scan_name}').value") == '', 'Search must not become the scan name'
    fill(scan_name, 'BWC506US additional view')
    assert js(group_value) == '2f27f08f-95fc-4297-a454-5e3cc0722b73', 'Editing the new case name must not erase an explicit group selection'

    js("document.querySelector('.source-selected button').click()")
    assert js(group_value) == '' and not js("document.querySelector('.source-selected')")
    assert js(f"document.querySelector('{scan_name}').value") == 'BWC506US additional view'
    held_out = js("(async () => (await (await fetch('/api/cases')).json()).find(x=>x.split==='test'))()")
    fill(search, held_out['name'])
    assert js("document.querySelector('.source-match').innerText.includes('Test')")
    assert js("!document.querySelector('.source-match button:not([disabled])')")
    assert js(group_value) == '', 'A held-out match must not fill the training field'
    fill(search, 'zz-no-such-case-98')
    assert js("document.querySelector('#case-lookup-status').textContent.includes('No matching')")
    js("document.querySelector('#source-new').click()")
    assert not js(f"document.querySelector('{search}')") and not js(f"document.querySelector('{group}').readOnly")
    fill(group, held_out['group_id'].upper())
    assert js("document.querySelector('#group-help').textContent.includes('held out')")
    fill(group, '2f27f08f-95fc-4297-a454-5e3cc0722b73')
    assert js("document.querySelector('#group-help').textContent.includes('already exists')")
    fill(group, 'known-independent-source')
    assert not js("document.querySelector('#group-help').textContent.includes('already exists')")
    js("document.querySelector('#source-existing').click()")
    assert js(group_value) == ''
    print('Add scan: separate search and name, locked selection, change group, new group, and held-out blocks passed.')
