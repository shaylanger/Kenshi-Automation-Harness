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
  status                                  phase (menu|loading|chargen|world), save, speed, squad
  load <save> | save <name>
  newgame <start name|sid> [edit] | import <save> [squad,buildings,research,npcs,relations,reset|all] [menu]
  speed <0|0.5..50>                       0 pauses
  chars [radius] | traders [radius]       characters near the player | real traders
  benches [radius] [crafts]               crafting benches: queue, needs, craft menu, contents
  craft <npc> <item> [at <bench>] [count n]   real craft worked by <npc> (supply materials, run the game)
  research <name> | blueprint <item>      complete research (test cheat); find research <text>
  research start|stop <name> | research status   real research at a bench: queue, progress, rate, benches
  find <character|squad|item|weapon|armour|container> <text>
  spawn <template> <faction> [near <npc> | at x y z] [count n] [dist m] [target <npc>] [size <mult>]
  where|inv|hp|sections|select|recruit|kill <npc>  (inv: inventory JSON incl. worn items;
                                          sections: inventory sections and their items)
  stat <npc> <stat|all> | setstat <npc> <stat> <value> | weight <npc|building>   (stat names: stat <npc> all)
  iteminfo|equip|unequip <npc> "<item name>"
  teleport <npc> <npc2 | x y z | building <name>> [dist m]
  ko <npc> [seconds] | health <npc> <percent> | hunger <npc> [0..300]
  attack <attacker> <target> | give <npc> <item> [n] | relation <npc> <-100..100>
  money <npc> <delta> | buy <buyer> <seller> <item> <price>
  stash <item> <n> [near <npc>]
  transfer <from npc> <to npc> <item> | craftfinish <npc> <item> [at <bench>]
  packput <npc> <pack> <item> [n] | packweight <npc|building|ground> <pack>
  order <npc> <task> [target <npc>] [building <b>] [keep] | tasks [filter] | fight <a> <b>
  job <npc> <building> [task <t>] [radius <m>] | jobs|clearjobs <npc>
  buildings [radius] [filter] [near <npc>] | building <name> [radius] | time
  build <building|sid> [near <npc> [dist m] | at x y z] [faction <f>] | unbuild <name> [radius]
  produced <building> [reset] [radius <m>]   units made since tracking/reset, per game hour
  power <building> on|off|charge|drain|supply|unsupply [radius <m>] | fill <building> <item> [n] [section <s>] [radius <m>]
  (radius: building searches, default 300, max 5000)
  setname <npc> <name> | faction <npc> <faction> | sleep <npc> [bed <b>] | wake <npc>
  damage <npc> <part> <cut> [blunt] [pierce] | blood <npc> <value|pct%> | eat <npc> <food>
  drop <npc> <item> [count] | pickup <npc> <item|#serial/index|nearest> [near <npc|building>] [radius <m>] [order|now]
                                          ground items; owned ones via the PICKUP order (theft path)
  stealth <npc> on|off | crime <npc> [radius <m>]   sneak mode | bounty, crime, HUNT_MY_THIEF hunters
  protect [<npc> on|off]                  test cheat: kept at full health, a KO cleared at once
  sever <npc> left_arm|right_arm|left_leg|right_leg [noitem] [ko]   real amputation (limb state stump)
  unload <npc> | reload <name>            stream his squad out / back in (game streaming)
  runspeed <npc> | walktime <npc> <dist> [+x|-x|+z|-z] [walk|run]   movement speeds | timed walk (seconds=, speed=)
  hit <attacker> <victim> <part> <damage>  cut wound credited to <attacker>, no fight (ko=yes|no)
  balance (KAH 24): chance <npc> ko|kidnap|lockpick|steal <target> [item <name>]   the game's own chance
  detect <sneaker> | detecttime <sneaker> <observer> [timeout <s>]   who notices him sneaking | time until seen
  senses <observer> <who>                                            does his AI see/hear him now (SensoryData)
  face <npc> <who>                                                   turn his whole body toward him; reply has sees=
  healtime <medic> <patient> [wound <cut>] [timeout <s>]   timed first aid (bandage_rate=)
  water <npc> | findwater <npc> [radius <m>] [depth <m>] | swimtime <npc> <dist> [+x|-x|+z|-z]   swimming
  construct <npc> <building> [dist <m>] | construction <building> [reset] [fill]   build-speed site + progress
  towns [filter,...] [max <n>]            towns/ruins nearest the player with pos=x,y,z
  shackle|unshackle <npc> | cage|uncage <npc> [cage] | shopstock <trader> [radius <m>]
  trade <buyer> <trader> <item> [radius <m>]   (shop storage radius: default 60, max 300)
  ui [filter] [all] | click <widget> | messages [n] | screenshot [name]
  fps [reset]                             avg/min fps, worst frame ms since launch or last reset
<npc> is a name (exact match nearest the player wins), #serial/index (as printed; #serial if unique),
@player or @selected.

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


_sent = [0]
LOCK_STALE_S = 30


def _take_lock(lock, deadline):
    """inbox.txt.lock, created exclusively: one writer at a time across
    processes (kah.py, stobe-say, background loops). A lock older than
    LOCK_STALE_S was left by a killed writer and is taken over."""
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, ('%d %f\n' % (os.getpid(), time.time())).encode())
            os.close(fd)
            return
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > LOCK_STALE_S:
                    os.remove(lock)
                    continue
            except OSError:
                continue  # released meanwhile
        if time.time() > deadline:
            sys.exit('inbox locked by another client for too long (%s)' % lock)
        time.sleep(0.05)


def write_command(d, line, deadline):
    """Puts one command line into inbox.txt without losing it to another
    writer (KAH 9): take the lock, wait until the harness has taken the
    previous inbox, write a temp file unique to this call, rename it in."""
    inbox = os.path.join(d, 'inbox.txt')
    lock = inbox + '.lock'
    _take_lock(lock, deadline)
    try:
        while os.path.exists(inbox):
            if time.time() > deadline:
                sys.exit('previous command still unread: is Kenshi running?')
            time.sleep(0.1)
        _sent[0] += 1
        tmp = '%s.%d.%d.tmp' % (inbox, os.getpid(), _sent[0])
        with open(tmp, 'w', newline='\n') as f:
            f.write(line + '\n')
        os.replace(tmp, inbox)
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


# Commands the game answers later (seconds the client waits by default).
LONG_COMMANDS = {'walktime': 200, 'pickup': 200, 'swimtime': 200, 'detecttime': 200, 'healtime': 200, 'hit': 60, 'acceltime': 150}


def send(d, cmd, args, timeout=None):
    if timeout is None:
        timeout = LONG_COMMANDS.get(cmd.lower(), 20)
    flag, outbox = (os.path.join(d, n) for n in ('enabled.flag', 'outbox.txt'))
    if not os.path.exists(flag):
        sys.exit('harness is off: run "kah on" (before launching Kenshi)')
    if any('\t' in a or '\n' in a for a in args):
        sys.exit('arguments may not contain tabs or newlines')
    deadline = time.time() + timeout
    # Unique across concurrent clients (a millisecond alone was not).
    cid = 'k%d_%d_%d' % (int(time.time() * 1000), os.getpid(), _sent[0] + 1)
    write_command(d, '\t'.join([cid, cmd] + args), deadline)
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
  @any <cmd> ~ <re> || <cmd> ~ <re>             alternatives in order until one passes (PASS names it);
                                      an alternative may be an @log / @log-wait or @set step
  @set NAME <command ...> ~ <regex with one (group)>   capture; later steps use ${NAME}
  @log <file> ~ <regex>               a line added to <file> since the run started matches
                                      (<file> may contain spaces; quotes optional)
  @log-wait <timeout_s> <file> ~ <regex>   same, but re-reads <file> every 1 s until
                                      a new line matches (instead of a fixed @sleep)
  @echo <text>
  # comment (blank lines ignored). Arguments are shell-quoted ("Dried Meat").
  Once the game was in the world, a step that finds it back at the main menu
  (no load/newgame sent since) ends the run: the rest is FAIL "not run". An
  @sleep of 60 s or more checks `status` every 30 s and ends early then."""


def log_step_path(line):
    """The file of an `@log <file> ~ <regex>` step: everything up to ' ~ ',
    so a path may contain spaces; quotes around it are dropped. Taken raw
    (shlex would eat Windows backslashes)."""
    rest = re.sub(r'^\s*@log(-wait\s+[0-9.]+)?\s+', '', line, count=1)
    if ' ~ ' in rest:
        rest = rest.split(' ~ ', 1)[0]
    rest = rest.strip()
    if len(rest) >= 2 and rest[0] == rest[-1] and rest[0] in ('"', "'"):
        rest = rest[1:-1]
    return rest


# Commands after which leaving the world is the scenario's own doing (a load,
# a new game): the world-lost stop (item 122) waits for the next world.
TRANSITION_COMMANDS = ('load', 'newgame', 'import', 'ui', 'click', 'key')
WATCH_SLEEP_MIN = 60   # an @sleep this long checks the game every WATCH_EVERY s
WATCH_EVERY = 30


def world_lost(detail):
    """'menu' when a reply says the game is back at the main menu (the whole
    squad died, or the world was left some other way), else None."""
    if re.search(r'no game loaded \(phase=menu\)|(^|\s)phase=menu\b', detail or ''):
        return 'menu'
    return None


def watched_sleep(d, seconds, every=WATCH_EVERY):
    """Sleeps <seconds>, asking `status` every <every> s; returns the reply
    that shows the game left the world (and ends the sleep early), else None."""
    end = time.time() + seconds
    while True:
        left = end - time.time()
        if left <= 0:
            return None
        time.sleep(min(every, left))
        try:
            ok, detail = send(d, 'status', [], timeout=15)
        except SystemExit:
            continue  # busy at high speed: try again at the next check
        if world_lost(detail):
            return detail


def run_scenario(d, path, csv_path=None, stop=False):
    import csv as csvmod
    import shlex
    variables = {}
    log_offsets = {}
    rows = []
    passed = failed = 0
    world_seen = False   # the scenario has seen the game world
    transition = False   # a load/new game was sent since: leaving the world is expected
    lost_at = None       # line where the game left the world (item 122)

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
    def log_step(step, regex):
        # @log / @log-wait <s> <file>: a line added to <file> since the run started matches <regex>
        file = log_step_path(step)
        m = re.match(r'\s*@log-wait\s+([0-9.]+)\s', step)
        start = time.time()
        end = start + (float(m.group(1)) if m else 0)
        while True:
            text = log_since(file)
            ok = bool(regex and re.search(regex, text))
            if ok or time.time() >= end:
                break
            time.sleep(1)
        if ok:
            return True, 'matched' + (' after %.0f s' % (time.time() - start) if m else '')
        return False, 'no new line matching in ' + file + (' within %s s' % m.group(1) if m else '')

    # Note the size of every log a step will look at, before anything runs (@log steps inside @any too).
    for line in lines:
        steps = line.strip()[5:].split(' || ') if line.strip().startswith('@any ') else [line]
        for step in steps:
            if re.match(r'\s*@log(-wait\s+[0-9.]+)?\s', step):
                file = to_local(log_step_path(step))
                log_offsets[file] = os.path.getsize(file) if os.path.exists(file) else 0
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if lost_at is not None:
            failed += 1
            rows.append((number, 'FAIL', raw.strip(), 'not run: the game left the world at line %d' % lost_at))
            continue
        line = subst(line)
        if line.startswith('@any '):
            # @any <step> [~ regex] || <step> [~ regex] ...: the alternatives run in order until one passes (a state
            # the game reaches by either of two paths, e.g. a crafted item still in the bench output or already
            # hauled by the worker); PASS names the alternative that matched, FAIL lists every reply.
            ok_step, tried = False, []
            for alt in line[5:].split(' || '):
                cmd, _, rx = alt.partition(' ~ ')
                try:
                    if re.match(r'@log(-wait\s+[0-9.]+)?\s', cmd.strip()):
                        # a log alternative: e.g. wait for progress, else re-issue the order (REL p7-04 m31)
                        ok_reply, detail = log_step(cmd.strip(), rx.strip())
                        rx = ''
                    elif cmd.strip().startswith('@set '):
                        # a capture alternative (PG 192 m35: read the dummy's hp, else prove the turret killed it)
                        words = shlex.split(cmd.strip())
                        ok_reply, detail = send(d, words[2], words[3:])
                        m = re.search(rx.strip() or '(.*)', detail) if ok_reply else None
                        ok_reply, rx = bool(m), ''
                        if m:
                            variables[words[1]] = m.group(1)
                            detail = '%s=%s' % (words[1], m.group(1))
                    else:
                        words = shlex.split(cmd.strip())
                        ok_reply, detail = send(d, words[0], words[1:])
                except SystemExit as e:
                    ok_reply, detail = False, str(e)
                except Exception as e:
                    ok_reply, detail = False, 'step error: %s' % e
                if ok_reply and (not rx.strip() or re.search(rx.strip(), detail)):
                    ok_step, detail = True, 'alt %d: %s' % (len(tried) + 1, detail)
                    break
                tried.append('alt %d: %s' % (len(tried) + 1, detail))
            if not ok_step:
                detail = 'no alternative matched: ' + ' | '.join(tried)
            passed += ok_step
            failed += not ok_step
            rows.append((number, 'PASS' if ok_step else 'FAIL', raw.strip(), detail))
            print('%s %3d %s => %s' % ('PASS' if ok_step else 'FAIL', number, raw.strip()[:90],
                                       detail.replace('\n', ' ')[:200]))
            sys.stdout.flush()
            if stop and not ok_step:
                break
            continue
        regex = None
        if ' ~ ' in line:
            line, regex = line.split(' ~ ', 1)
            line = line.strip()
        ok_step, detail = True, ''
        try:
            if re.match(r'@log(-wait\s+[0-9.]+)?\s', line):
                ok_step, detail = log_step(line, regex)
            elif line.startswith('@'):
                words = shlex.split(line[1:])
                kind = words[0]
                if kind == 'sleep':
                    seconds = float(words[1])
                    if world_seen and not transition and seconds >= WATCH_SLEEP_MIN:
                        reply = watched_sleep(d, seconds, WATCH_EVERY)
                        if reply:
                            ok_step, detail = False, 'game left the world during the sleep: ' + reply
                    else:
                        time.sleep(seconds)
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
                else:
                    ok_step, detail = False, 'unknown step @' + kind
            else:
                expect_error = line.startswith('!')
                words = shlex.split(line.lstrip('!').strip())
                ok_reply, detail = send(d, words[0], words[1:])
                if words[0].lower() in TRANSITION_COMMANDS:
                    transition = True
                ok_step = ok_reply != expect_error
                if ok_step and regex and not re.search(regex, detail):
                    ok_step = False
                    detail = 'no match for /%s/: %s' % (regex, detail)
        except SystemExit as e:
            ok_step, detail = False, str(e)
        except Exception as e:  # malformed step
            ok_step, detail = False, 'step error: %s' % e
        if 'phase=world' in (detail or ''):
            world_seen, transition = True, False
        if not ok_step and world_seen and not transition and world_lost(detail):
            lost_at = number
            detail = 'ABORT: the game left the world (phase=menu: squad dead or world closed); ' \
                     'remaining steps not run. ' + (detail or '')
        passed += ok_step
        failed += not ok_step
        rows.append((number, 'PASS' if ok_step else 'FAIL', raw.strip(), detail))
        print('%s %3d %s => %s' % ('PASS' if ok_step else 'FAIL', number, raw.strip()[:90],
                                   detail.replace('\n', ' ')[:200]))
        sys.stdout.flush()
        if stop and not ok_step:
            break
    if lost_at is not None:
        print('ABORT at line %d: the game left the world; %d steps not run' %
              (lost_at, sum(1 for r in rows if r[3].startswith('not run:'))))
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
