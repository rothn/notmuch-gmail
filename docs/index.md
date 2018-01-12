# notmuch-gmail-sync

Bidirectional sync of Gmail messages with notmuch database.

![Logo](https://github.com/rjarry/notmuch-gmail-sync/raw/master/docs/logo.png)

## Description

`notmuch-gmail-sync` is a command line application that can pull email and
labels (and changes to labels) from your Gmail account and store them locally
in a maildir with the labels synchronized with a notmuch database. The changes
to tags in the notmuch database may be pushed back remotely to your Gmail
account.

## Installation

TODO

## Quickstart

TODO

## Configuration & Advanced Usage

TODO

## Privacy Policy

* `notmuch-gmail-sync` is a **local** command line application. It uses OAuth2
  to access your Gmail data and will **NOT** share anything with anyone.

* `notmuch-gmail-sync` uses the Gmail web API to access (READ) your messages
  and labels.

* `notmuch-gmail-sync` uses the Gmail web API to change (ADD, REMOVE) the
  labels associated with messages.

* `notmuch-gmail-sync` uses the Gmail web API to change (ADD, REMOVE) your
  Gmail labels.

* `notmuch-gmail-sync` will not and can not:

  - Add or delete messages on your remote account (except syncing the `trash`
    or `spam` label to messages, and those messages will eventually be
    [deleted](https://support.google.com/mail/answer/7401?co=GENIE.Platform%3DDesktop&hl=en))

  - Modify messages other than their labels

* `notmuch-gmail-sync` is free software released under the [MIT
  license](https://opensource.org/licenses/MIT) and comes with **NO
  WARRANTIES**.