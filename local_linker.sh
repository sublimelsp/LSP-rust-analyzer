#! /bin/bash

# It creates the symbolic link from this source package to sublime package

SUBLIME_PACKAGE="/Users/msz/Library/Application Support/Sublime Text 3/Packages/LSP-rust-analyzer"
SOURCE_PACKAGE=`pwd`

if [ -L "$SUBLIME_PACKAGE" ];
then
    echo "Link '$SUBLIME_PACKAGE' exists"
else
    echo "Link '$SUBLIME_PACKAGE' does not exist. Will be created"
    ln -s "$SOURCE_PACKAGE" "$SUBLIME_PACKAGE"
fi
