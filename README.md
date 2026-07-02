# mkdaemonuser

A script to create a daemon user account on macOS and other Unix systems.

## Why?

Creating a user account for a daemon is notoriously finicky on macOS (and even if you think
you know how to do it, macOS can surprise you by mucking it up upon OS upgrade).

On other Unix systems the situation is much better, but there are still different tools with
subtly different semantics and gotchas.

This script aims to make it easy and portable to create a daemon user (and group) account
on all these platforms.

## Prerequisites

* Python 3.10 or above.
* macOS, Linux, {Free|Net|Open|DragonFly}BSD, illumos or Haiku.

## Installation

If you have curl:

```bash
curl -fsSL https://github.com/gershnik/mkdaemonuser/releases/latest/download/mkdaemonuser | \
    sudo tee /usr/local/bin/mkdaemonuser >/dev/null && \
    sudo chmod a+x /usr/local/bin/mkdaemonuser
```

Or, if you prefer wget:

```bash
wget -qO- https://github.com/gershnik/mkdaemonuser/releases/latest/download/mkdaemonuser | \
    sudo tee /usr/local/bin/mkdaemonuser >/dev/null && \
    sudo chmod a+x /usr/local/bin/mkdaemonuser
```

Or grab the `mkdaemonuser` file from this repo manually, put it somewhere in your PATH and
make it executable.

## Usage

```
usage: mkdaemonuser [-h] -c FULL_NAME -d HOME_DIRECTORY [-s SHELL] login

Create a daemon user and a matching group.

positional arguments:
  login                 name for both the user and the group

options:
  -h, --help            show this help message and exit
  -c, --comment FULL_NAME
                        full name (GECOS); applied to both the user and the group
  -d, --home-dir HOME_DIRECTORY
                        home directory for the account
  -s, --shell SHELL     login shell (default: a platform-appropriate locked shell)
```

The script must be run as root (duh!).

The account is created with login disabled and the login shell, unless you override it, 
is something like `[/usr]/bin/false` or `[/usr]/sbin/nologin`, as 
appropriate for each platform.

