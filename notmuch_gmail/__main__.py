# Copyright (c) 2018 Robin Jarry
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
Bidirectional sync of Gmail messages with a notmuch database.
"""

import argparse
import logging
import os

from .config import Config
from .gapi import GmailAPI, GAPIError
from .maildir import Maildir
from .util import human_size, configure_logging


LOG = logging.getLogger(__name__)

#------------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        '-c', '--config',
        metavar='PATH',
        default=os.environ.get('NOTMUCH_GMAIL_CONFIG', '~/.notmuch-gmail-config'),
        type=os.path.expanduser,
        help='''
        Path to config file
        [default: $NOTMUCH_GMAIL_CONFIG or ~/.notmuch-gmail-config]
        ''',
        )
    parser.add_argument(
        '-n', '--no-browser',
        default=False,
        action='store_true',
        help='Do not try to open a web browser for authentication',
        )
    parser.add_argument(
        '--force-reauth',
        default=False,
        action='store_true',
        help='Ignore existing credentials and force re-authentication',
        )
    parser.add_argument(
        '--local-wins',
        default=False,
        action='store_true',
        help='''
        In case of conflicting changes between local and remote (tags/labels
        changed on both sides on the same messages), favor the local version
        and replace the remote version with it. By default, remote side (Gmail)
        wins.
        ''',
        )
    parser.add_argument(
        '--defconfig',
        action='store_true',
        default=False,
        help='''
        Print the default configuration on standard output.
        Redirect output to ~/.notmuch-gmail-config and modify the
        file according to your needs.
        ''',
        )
    parser.add_argument(
        '-v', '--verbose',
        default=False,
        action='store_true',
        help='Be more verbose',
        )

    return parser.parse_args()

#------------------------------------------------------------------------------
class HistoryError(Exception):
    pass

#------------------------------------------------------------------------------
class Changes(object):
    def __init__(self, l_updated, l_new, r_updated, r_new, r_deleted):
        self.l_updated = l_updated
        self.l_new = l_new
        self.r_updated = r_updated
        self.r_new = r_new
        self.r_deleted = r_deleted

#------------------------------------------------------------------------------
class NotmuchGmailSync(object):

    def __init__(self, config_filepath, force_reauth=False,
                 no_browser=False, local_wins=False):
        self.config = Config(config_filepath)
        self.api = GmailAPI(self.config)
        self.mdir = Maildir(self.config)
        self.force_reauth = force_reauth
        self.no_browser = no_browser
        self.local_wins = local_wins

    def auth(self):
        LOG.info('Authorizing connection...')
        credentials = self.config.get_credentials()
        if self.force_reauth or not credentials or credentials.invalid:
            self.api.authenticate(self.no_browser)
        self.api.authorize()

    def changes_incremental(self):
        last_history_id = self.config.get_last_history_id()
        if last_history_id is None:
            raise HistoryError('No history yet')

        LOG.info('Fetching last changes from Gmail...')
        try:
            r_updated, r_new, r_deleted = self.api.get_changes(last_history_id)
        except GAPIError:
            raise HistoryError('Last known history is too old')

        LOG.info('Detecting local changed messages...')
        l_updated, l_new = self.mdir.get_changes()

        return Changes(l_updated=l_updated, l_new=l_new,
                       r_updated=r_updated, r_new=r_new, r_deleted=r_deleted)

    def changes_full(self):
        LOG.info('Detecting changed local messages...')
        l_updated, l_new = self.mdir.get_changes()
        all_local = self.mdir.all_messages()

        LOG.info('Fetching all message IDs...')
        batch = 0
        r_all = set()
        r_new = set()
        for estimate, ids in self.api.all_ids():
            batch += 1
            batch_new = 0
            for i in ids:
                r_all.add(i)
                if i not in all_local:
                    r_new.add(i)
                    batch_new += 1
            if batch < estimate:
                comment = 'approx. %d batches left' % (estimate - batch)
            else:
                comment = "wait, there's more..."
            LOG.info('[batch #%03d] fetched %d IDs, %d new (%s)',
                     batch, len(ids), batch_new, comment)

        LOG.info('Looking for remote message deletions...')
        r_deleted = r_all - all_local.keys()
        local_ids = all_local.keys() - r_deleted

        r_updated = {}
        LOG.info('Fetching remote tags changes for known messages...')
        num_local = len(local_ids)

        counter = '[%{0}d/%{0}d]'.format(len(str(num_local)))
        n = 0
        def callback(msg):
            nonlocal n
            n += 1
            if all_local[msg['id']] == msg['tags']:
                LOG.info(counter + ' message %r not changed',
                         n, num_local, msg['id'])
                return

            r_updated[msg['id']] = msg['tags']
            LOG.info(counter + ' message %r new tags: %s',
                     n, num_local, msg['id'], msg['tags'])

        self.api.get_content(local_ids, callback)

        return Changes(l_updated=l_updated, l_new=l_new,
                       r_updated=r_updated, r_new=r_new, r_deleted=r_deleted)

    def fetch(self, new_ids):
        LOG.info('Fetching new messages...')

        num_new = len(new_ids)
        counter = '[%{0}d/%{0}d]'.format(len(str(num_new)))
        n = 0
        def callback(msg):
            nonlocal n
            self.mdir.store_and_index(msg)
            n += 1
            size = human_size(msg['sizeEstimate'])
            LOG.info(counter + ' fetched message %r %s', n, num_new, msg['id'], size)
        self.api.get_content(new_ids, callback, fmt='raw')

    def merge(self, local_updated, remote_updated):
        LOG.info('Resolving conflicts...')

        conflicts = local_updated.keys() & remote_updated.keys()
        if conflicts:
            LOG.info('Found %d conflicts', len(conflicts))
            if self.local_wins:
                LOG.info('Dropping %d remote changes (--local-wins)',
                         len(conflicts))
                for c in conflicts:
                    del remote_updated[c]
            else:
                LOG.info('Dropping %d local changes', len(conflicts))
                for c in conflicts:
                    del local_updated[c]

        LOG.info('Pushing local tag changes...')
        self.api.push_tags(local_updated)
        LOG.info('Applying remote tag changes...')
        self.mdir.apply_tags(remote_updated)

    def run(self):
        # only create user readable/writable files and folders
        os.umask(0o077)

        self.auth()
        LOG.info('Fetching Gmail labels...')
        self.api.update_labels()

        try:
            changes = self.changes_incremental()
        except HistoryError as e:
            LOG.info('%s. A full sync is required.', e)
            changes = self.changes_full()

        self.fetch(changes.r_new)
        self.merge(changes.l_updated, changes.r_updated)
        # TODO: push sent/drafts & delete
        # self.push(changes.l_new)
        # self.delete(changes.r_deleted)

#------------------------------------------------------------------------------
def main():
    try:
        args = parse_args()

        if args.defconfig:
            print(Config.DEFAULT.strip())
            return 0

        configure_logging(args.verbose)

        sync = NotmuchGmailSync(
            args.config, force_reauth=args.force_reauth,
            no_browser=args.no_browser, local_wins=args.local_wins)

        sync.run()

        return 0

    except (EOFError, KeyboardInterrupt):
        return 2
    except GAPIError as e:
        LOG.error('error: %s', e)
        return 1