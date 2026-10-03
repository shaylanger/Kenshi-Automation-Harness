#!/usr/bin/env python3
"""kah: drive a running Kenshi through the Kenshi Automation Harness.

  kah on | off                       enable/disable the harness (enabled.flag; autosave
                                     is off and the game runs unfocused while enabled)
  kah autoload <save>                load <save> as soon as the main menu is up
  kah wait-world [timeout_s]         wait until a save is loaded and the world runs
  kah wait-game <minutes> [timeout_s]  wait for game time to pass (game must be running)
  kah run <scenario file> [--csv out.csv] [--stop]   run a test scenario (kah run --help)
  kah help                           every command the running game knows (incl. mods)
  kah <command> [args...]            send one command, print the reply

Built-in commands:
  status                                  phase (menu|loading|world), save, speed, squad
  load <save> | save <name>
  speed <0|0.5..50>                       0 pauses
  chars [radius] | traders [radius]       characters near the player | real traders
  benches [radius] [crafts]               crafting benches: queue, needs, craft menu, contents
  craft <npc> <item> [at <bench>] [count n]   real craft worked by <npc> (supply materials, run the game)
  research <name> | blueprint <item>      complete research (test cheat); find research <text>
  find <character|squad|item|weapon|armour|container> <text>
  spawn <template> <faction> [near <npc> | at x y z] [count n] [dist m] [target <npc>] [size <mult>]
  where|inv|hp|sections|select|recruit|kill <npc>  (inv: inventory JSON incl. worn items;
                                          sections: inventory sections and their items)
  stat <npc> <stat> | setstat <npc> <stat> <value> | weight <npc>
  iteminfo|equip|unequip <npc> "<item name>"
  teleport <npc> <npc2 | x y z | building <name>> [dist m]
  ko <npc> [seconds] | health <npc> <percent> | hunger <npc> <0..300>
  attack <attacker> <target> | give <npc> <item> [n] | relation <npc> <-100..100>
  money <npc> <delta> | buy <buyer> <seller> <item> <price>
  stash <item> <n> [near <npc>]
  transfer <from npc> <to npc> <item> | craftfinish <npc> <item> [at <bench>]
  packput <npc> <pack> <item> [n] | packweight <npc> <pack>
  order <npc> <task> [target <npc>] [building <b>] [keep] | tasks [filter] | fight <a> <b>
  job <npc> <building> [task <t>] [radius <m>] | jobs|clearjobs <npc>
  buildings [radius] [filter] [near <npc>] | building <name> [radius] | time
  power <building> on|off|charge [radius <m>] | fill <building> <item> [n] [section <s>] [radius <m>]
  (radius: building searches, default 300, max 5000)
  setname <npc> <name> | faction <npc> <faction> | sleep <npc> [bed <b>] | wake <npc>
  damage <npc> <part> <cut> [blunt] [pierce] | blood <npc> <value|pct%> | eat <npc> <food>
  shackle|unshackle <npc> | cage|uncage <npc> [cage] | shopstock <trader>
  trade <buyer> <trader> <item>
  ui [filter] [all] | click <widget> | messages [n] | screenshot [name]
<npc> is a name (exact match nearest the player wins), #serial, @player or @selected.

The harness folder is the installed mod folder (Kenshi\\mods\\AutomationHarness):
set KAH_DIR to it, or pass --dir <path> first. Works from Windows and WSL.
"""
import os
import re
import sys
import time

DEFAULT_DIRS = [
    r'C:\Program Files (x86)\Steam\steamapps\common\Kenshi\mods\AutomationHarness',
    r'D:\Steam\steamapps\common\Kenshi\mods\AutomationHarness',
    r'D:\SteamLibrary\steamapps\common\Kenshi\mods\AutomationHarness',
]


def to_local(path):
    """C:\\x\\y -> /mnt/c/x/y when running under WSL/Linux."""
    if os.name == 'nt' or len(path) < 2 or path[1] != ':':
        return path
    return '/mnt/' + path[0].lower() + path[2:].replace('\\', '/')


def harness_dir(argv):
    given, rest = None, argv
    if len(argv) >= 2 and argv[0] == '--dir':
        given, rest = argv[1], argv[2:]
    elif os.environ.get('KAH_DIR'):
        given = os.environ['KAH_DIR']
    if given:
        if not os.path.isdir(to_local(given)):
            sys.exit('no such folder: %s' % given)
        return to_local(given), rest
    for d in DEFAULT_DIRS:
        if os.path.isdir(to_local(d)):
            return to_local(d), argv
    sys.exit('harness folder not found: set KAH_DIR or pass --dir <Kenshi\\mods\\AutomationHarness>')


def send(d, cmd, args, timeout=20):
    flag, inbox, outbox = (os.path.join(d, n) for n in ('enabled.flag', 'inbox.txt', 'outbox.txt'))
    if not os.path.exists(flag):
        sys.exit('harness is off: run "kah on" (before launching Kenshi)')
    if any('\t' in a or '\n' in a for a in args):
        sys.exit('arguments may not contain tabs or newlines')
    deadline = time.time() + timeout
    while os.path.exists(inbox):
        if time.time() > deadline:
            sys.exit('previous command still unread: is Kenshi running?')
        time.sleep(0.2)
    cid = 'k%d' % int(time.time() * 1000)
    tmp = inbox + '.tmp'
    with open(tmp, 'w', newline='\n') as f:
        f.write('\t'.join([cid, cmd] + args) + '\n')
    os.replace(tmp, inbox)
    while time.time() < deadline:
        if os.path.exists(outbox):
            with open(outbox, encoding='utf-8', errors='replace') as f:
                for line in f:
                    parts = line.rstrip('\n').split('\t', 2)
                    if parts[0] == cid and len(parts) == 3:
                        return parts[1] == 'ok', parts[2]
        time.sleep(0.2)
    sys.exit('no answer within %ds (Kenshi not running or stuck loading?)' % timeout)


def wait_world(d, limit):
    end = time.time() + limit
    detail = ''
    while time.time() < end:
        try:
            ok, detail = send(d, 'status', [], timeout=10)
        except SystemExit:
            ok, detail = False, 'no answer (loading?)'
        if ok and 'phase=world' in detail:
            return True, detail
        time.sleep(2)
    return False, 'world not ready after %ds: %s' % (limit, detail)


def game_hours(d):
    ok, detail = send(d, 'time', [], timeout=15)
    m = re.search(r'game_hours=([0-9.]+)', detail) if ok else None
    if not m:
        sys.exit('time: ' + detail)
    return float(m.group(1)), detail


def wait_game(d, minutes, limit):
    """Waits until <minutes> of game time have passed (the game must be running)."""
    start, detail = game_hours(d)
    if 'paused=1' in detail:
        return False, 'the game is paused (speed 0): game time does not pass'
    end = time.time() + limit
    while time.time() < end:
        now, detail = game_hours(d)
        if (now - start) * 60.0 >= minutes:
            return True, '%.1f game minutes passed' % ((now - start) * 60.0)
        time.sleep(1)
    now, detail = game_hours(d)
    return False, 'only %.1f of %s game minutes after %ds' % ((now - start) * 60.0, minutes, limit)


SCENARIO_HELP = """Scenario file (kah run <file> [--csv out.csv] [--stop]): one step per line.
  <command args...>                   must answer ok
  ! <command args...>                 must answer error
  <command ...> ~ <regex>             must answer ok and match <regex>
  @sleep <seconds>
  @wait-world [timeout_s]
  @wait-game <minutes> [timeout_s]
  @until <timeout_s> <command ...> ~ <regex>   repeat (every 2 s) until the reply matches
  @set NAME <command ...> ~ <regex with one (group)>   capture; later steps use ${NAME}
  @log <file> ~ <regex>               a line added to <file> since the run started matches
  @echo <text>
  # comment (blank lines ignored). Arguments are shell-quoted ("Dried Meat")."""


def run_scenario(d, path, csv_path=None, stop=False):
    import csv as csvmod
    import shlex
    variables = {}
    log_offsets = {}
    rows = []
    passed = failed = 0

    def subst(text):
        return re.sub(r'\$\{(\w+)\}', lambda m: variables.get(m.group(1), m.group(0)), text)

    def log_since(file):
        file = to_local(file)
        if not os.path.exists(file):
            return ''
        with open(file, 'rb') as f:
            f.seek(log_offsets.get(file, 0))
            return f.read().decode('utf-8', 'replace')

    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()
    # Note the size of every log a step will look at, before anything runs.
    for line in lines:
        m = re.match(r'\s*@log\s+(\S+)', line)
        if m:
            file = to_local(m.group(1))
            log_offsets[file] = os.path.getsize(file) if os.path.exists(file) else 0
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        line = subst(line)
        regex = None
        if ' ~ ' in line:
            line, regex = line.split(' ~ ', 1)
            line = line.strip()
        ok_step, detail = True, ''
        try:
            if line.startswith('@'):
                words = shlex.split(line[1:])
                kind = words[0]
                if kind == 'sleep':
                    time.sleep(float(words[1]))
                elif kind == 'echo':
                    detail = ' '.join(words[1:])
                elif kind == 'wait-world':
                    ok_step, detail = wait_world(d, float(words[1]) if len(words) > 1 else 300)
                elif kind == 'wait-game':
                    ok_step, detail = wait_game(d, float(words[1]),
                                                float(words[2]) if len(words) > 2 else 600)
                elif kind == 'until':
                    end = time.time() + float(words[1])
                    ok_step = False
                    while time.time() < end:
                        ok_reply, detail = send(d, words[2], words[3:])
                        if ok_reply and (not regex or re.search(regex, detail)):
                            ok_step = True
                            break
                        time.sleep(2)
                elif kind == 'set':
                    name = words[1]
                    ok_reply, detail = send(d, words[2], words[3:])
                    m = re.search(regex or '(.*)', detail) if ok_reply else None
                    ok_step = bool(m)
                    if m:
                        variables[name] = m.group(1)
                        detail = '%s=%s' % (name, m.group(1))
                elif kind == 'log':
                    # The path is taken raw (shlex would eat Windows backslashes).
                    words[1] = re.match(r'\s*@log\s+(\S+)', line).group(1)
                    text = log_since(words[1])
                    ok_step = bool(regex and re.search(regex, text))
                    detail = 'matched' if ok_step else 'no new line matching in ' + words[1]
                else:
                    ok_step, detail = False, 'unknown step @' + kind
            else:
                expect_error = line.startswith('!')
                words = shlex.split(line.lstrip('!').strip())
                ok_reply, detail = send(d, words[0], words[1:])
                ok_step = ok_reply != expect_error
                if ok_step and regex and not re.search(regex, detail):
                    ok_step = False
                    detail = 'no match for /%s/: %s' % (regex, detail)
        except SystemExit as e:
            ok_step, detail = False, str(e)
        except Exception as e:  # malformed step
            ok_step, detail = False, 'step error: %s' % e
        passed += ok_step
        failed += not ok_step
        rows.append((number, 'PASS' if ok_step else 'FAIL', raw.strip(), detail))
        print('%s %3d %s => %s' % ('PASS' if ok_step else 'FAIL', number, raw.strip()[:90],
                                   detail.replace('\n', ' ')[:200]))
        sys.stdout.flush()
        if stop and not ok_step:
            break
    print('== %d passed, %d failed (%s)' % (passed, failed, path))
    if csv_path:
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            w = csvmod.writer(f)
            w.writerow(['line', 'result', 'step', 'detail'])
            w.writerows(rows)
    return 0 if failed == 0 else 1


def main():
    d, argv = harness_dir(sys.argv[1:])
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    if cmd == 'on':
        open(os.path.join(d, 'enabled.flag'), 'w').close()
        print('harness on (%s)' % d)
        return 0
    if cmd == 'off':
        try:
            os.remove(os.path.join(d, 'enabled.flag'))
        except FileNotFoundError:
            pass
        print('harness off')
        return 0
    if cmd == 'autoload':
        if len(args) != 1:
            sys.exit('usage: kah autoload <save>')
        with open(os.path.join(d, 'autoload.txt'), 'w', newline='') as f:
            f.write(args[0])
        print('autoload %s' % args[0])
        return 0
    if cmd == 'wait-world':
        ok, detail = wait_world(d, float(args[0]) if args else 300)
        print(detail)
        return 0 if ok else 1
    if cmd == 'wait-game':
        if not args:
            sys.exit('usage: kah wait-game <game minutes> [timeout_s]')
        ok, detail = wait_game(d, float(args[0]), float(args[1]) if len(args) > 1 else 600)
        print(detail)
        return 0 if ok else 1
    if cmd == 'run':
        if not args or args[0] in ('-h', '--help'):
            print(SCENARIO_HELP)
            return 0
        csv_path = args[args.index('--csv') + 1] if '--csv' in args else None
        return run_scenario(d, args[0], csv_path, '--stop' in args)
    ok, detail = send(d, cmd, args)
    print(('' if ok else 'ERROR: ') + detail)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
