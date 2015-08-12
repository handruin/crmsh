# Copyright (C) 2008-2011 Dejan Muhamedagic <dmuhamedagic@suse.de>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

import sys
import os
import getopt
import atexit
import random

import config
import options
import constants
from msg import err_buf, common_err
import clidisplay
import term
import utils
import userdir

import ui_root
import ui_context


random.seed()


def load_rc(context, rcfile):
    # only load the RC file if there is no new-style user config
    if config.has_user_config():
        return

    try:
        f = open(rcfile)
    except:
        return
    save_stdin = sys.stdin
    sys.stdin = f
    while True:
        inp = utils.multi_input()
        if inp is None:
            break
        try:
            if not context.run(inp):
                raise ValueError("Error in RC file: " + rcfile)
        except ValueError, msg:
            common_err(msg)
    f.close()
    sys.stdin = save_stdin


def exit_handler():
    '''
    Write the history file. Remove tmp files.
    '''
    if options.interactive and not options.batch:
        try:
            from readline import write_history_file
            write_history_file(userdir.HISTORY_FILE)
        except:
            pass


# prefer the user set PATH
def envsetup():
    mybinpath = os.path.dirname(sys.argv[0])
    for p in mybinpath, config.path.crm_daemon_dir:
        if p not in os.environ["PATH"].split(':'):
            os.environ['PATH'] = "%s:%s" % (os.environ['PATH'], p)


# three modes: interactive (no args supplied), batch (input from
# a file), half-interactive (args supplied, but not batch)
def cib_prompt():
    shadow = utils.get_cib_in_use()
    if not shadow:
        return constants.live_cib_prompt
    if constants.tmp_cib:
        return constants.tmp_cib_prompt
    return shadow


def usage(rc):
    f = sys.stderr
    if rc == 0:
        f = sys.stdout
    print >> f, """Usage: crm [OPTIONS] [SUBCOMMAND ARGS...]

    -f, --file='FILE'::
        Load commands from the given file. If a dash `-` is used in place
        of a file name, `crm` will read commands from the shell standard
        input (`stdin`).

    -c, --cib='CIB'::
        Start the session using the given shadow CIB file.
        Equivalent to `cib use <CIB>`.

    -D, --display='OUTPUT_TYPE'::
        Choose one of the output options: plain, color, or
        uppercase. The default is color if the terminal emulation
        supports colors. Otherwise, plain is used.

    -F, --force::
        Make `crm` proceed with applying changes where it would normally
        ask the user to confirm before proceeding. This option is mainly
        useful in scripts, and should be used with care.

    -w, --wait::
        Make crm wait for the cluster transition to finish (for the
        changes to take effect) after each processed line.

    -H, --history*='DIR|FILE|SESSION'::
        A directory or file containing a cluster report to load
        into the `history` commands, or the name of a previously
        saved history session.

    -h, --help::
        Print help page.

    --version::
        Print crmsh version and build information (Mercurial Hg changeset
        hash).

    -d, --debug::
        Print verbose debugging information.

    -R, --regression-tests::
        Enables extra verbose trace logging used by the regression
        tests. Logs all external calls made by crmsh.

    --scriptdir='DIR'::
        Extra directory where crm looks for cluster scripts. Can be
        a semicolon-separated list of directories.

    Use crm without arguments for an interactive session.
    Supply one or more arguments for a "single-shot" use.
    Supply level name to start working at that level.
    Specify with -f a file which contains a script. Use '-' for
    standard input or use pipe/redirection.

    Examples:

        # crm -f stopapp2.txt
        # crm -w resource stop global_www
        # echo stop global_www | crm resource
        # crm configure property no-quorum-policy=ignore
        # crm ra info pengine
        # crm status

    See the crm(8) man page or the crm help system for more details.
    """
    sys.exit(rc)


def set_interactive():
    '''Set the interactive option only if we're on a tty.'''
    if utils.can_ask():
        options.interactive = True


def compatibility_setup():
    if not utils.is_pcmk_118():
        del constants.attr_defaults["node"]
        constants.cib_no_section_rc = 22


def add_quotes(args):
    '''
    Add quotes if there's whitespace in one of the
    arguments; so that the user doesn't need to protect the
    quotes.

    If there are two kinds of quotes which actually _survive_
    the getopt, then we're _probably_ screwed.

    At any rate, stuff like ... '..."..."'
    as well as '...\'...\''  do work.
    '''
    l = []
    for s in args:
        if config.core.add_quotes and ' ' in s:
            q = '"' in s and "'" or '"'
            if q not in s:
                s = "%s%s%s" % (q, s, q)
        l.append(s)
    return l


def do_work(context, user_args):
    compatibility_setup()

    if options.shadow:
        if not context.run("cib use " + options.shadow):
            return 1

    # this special case is silly, but we have to keep it to
    # preserve the backward compatibility
    if len(user_args) == 1 and user_args[0].startswith("conf"):
        if not context.run("configure"):
            return 1
    elif len(user_args) > 0:
        # we're not sure yet whether it's an interactive session or not
        # (single-shot commands aren't)
        err_buf.reset_lineno()
        options.interactive = False

        l = add_quotes(user_args)
        if context.run(' '.join(l)):
            # if the user entered a level, then just continue
            if not context.previous_level():
                return 0
            set_interactive()
            if options.interactive:
                err_buf.reset_lineno(-1)
        else:
            return 1

    if options.input_file and options.input_file != "-":
        try:
            sys.stdin = open(options.input_file)
        except IOError, msg:
            common_err(msg)
            usage(2)

    if options.interactive and not options.batch:
        context.setup_readline()

    rc = 0
    while True:
        try:
            rendered_prompt = constants.prompt
            if options.interactive and not options.batch:
                # TODO: fix how color interacts with readline,
                # seems the color prompt messes it up
                promptstr = "crm(%s)%s# " % (cib_prompt(), context.prompt())
                constants.prompt = promptstr
                if clidisplay.colors_enabled():
                    rendered_prompt = term.render(clidisplay.prompt(promptstr))
                else:
                    rendered_prompt = promptstr
            inp = utils.multi_input(rendered_prompt)
            if inp is None:
                if options.interactive:
                    rc = 0
                context.quit(rc)
            try:
                if not context.run(inp):
                    rc = 1
            except ValueError, msg:
                rc = 1
                common_err(msg)
        except KeyboardInterrupt:
            if options.interactive and not options.batch:
                print "Ctrl-C, leaving"
            context.quit(1)
    return rc


def compgen():
    args = sys.argv[2:]
    if len(args) < 2:
        return

    options.shell_completion = True

    # point = int(args[0])
    line = args[1]

    # remove [*]crm from commandline
    idx = line.find('crm')
    if idx >= 0:
        line = line[idx+3:].lstrip()

    options.interactive = False
    ui = ui_root.Root()
    context = ui_context.Context(ui)
    last_word = line.rsplit(' ', 1)
    if len(last_word) > 1 and ':' in last_word[1]:
        idx = last_word[1].rfind(':')
        for w in context.complete(line):
            print w[idx+1:]
    else:
        for w in context.complete(line):
            print w


def parse_options():
    try:
        opts, user_args = getopt.getopt(
            sys.argv[1:],
            'whdc:f:FX:RD:H:',
            ("wait", "version", "help", "debug",
             "cib=", "file=", "force", "profile=",
             "regression-tests", "display=", "history=",
             "scriptdir="))
        for o, p in opts:
            if o in ("-h", "--help"):
                usage(0)
            elif o == "--version":
                print >> sys.stdout, ("%s" % config.CRM_VERSION)
                sys.exit(0)
            elif o == "-d":
                config.core.debug = "yes"
            elif o == "-X":
                options.profile = p
            elif o == "-R":
                options.regression_tests = True
            elif o in ("-D", "--display"):
                config.color.style = p
            elif o in ("-F", "--force"):
                config.core.force = "yes"
            elif o in ("-f", "--file"):
                options.batch = True
                options.interactive = False
                err_buf.reset_lineno()
                options.input_file = p
            elif o in ("-H", "--history"):
                options.history = p
            elif o in ("-w", "--wait"):
                config.core.wait = "yes"
            elif o in ("-c", "--cib"):
                options.shadow = p
            elif o == "--scriptdir":
                options.scriptdir = p
        return user_args
    except getopt.GetoptError, msg:
        print msg
        usage(1)


def profile_run(context, user_args):
    import cProfile
    cProfile.runctx('do_work(context, user_args)',
                    globals(),
                    {'context': context, 'user_args': user_args},
                    filename=options.profile)
    # print how to use the profile file, but don't disturb
    # the regression tests
    if not options.regression_tests:
        stats_cmd = "; ".join(['import pstats',
                               's = pstats.Stats("%s")' % options.profile,
                               's.sort_stats("cumulative").print_stats()'])
        print "python -c '%s' | less" % (stats_cmd)
    return 0


def run():
    try:
        if len(sys.argv) >= 2 and sys.argv[1] == '--compgen':
            compgen()
            return 0
        envsetup()
        userdir.mv_user_files()

        ui = ui_root.Root()
        context = ui_context.Context(ui)

        load_rc(context, userdir.RC_FILE)
        atexit.register(exit_handler)
        options.interactive = utils.can_ask()
        if not options.interactive:
            err_buf.reset_lineno()
            options.batch = True
        user_args = parse_options()
        if options.profile:
            return profile_run(context, user_args)
        else:
            return do_work(context, user_args)
    except KeyboardInterrupt:
        print "Ctrl-C, leaving"
        sys.exit(1)
    except ValueError, e:
        common_err(str(e))

# vim:ts=4:sw=4:et:
