#! /bin/bash

# It creates the symbolic link from this source package to sublime package


if [[ "$OSTYPE" == "linux-gnu" ]];
then
    SUBLIME_PACKAGE="$HOME/.config/sublime-text-3/Packages/LSP-rust-analyzer"
else
    SUBLIME_PACKAGE="$HOME/Library/Application Support/Sublime Text 3/Packages/LSP-rust-analyzer"
fi

SOURCE_PACKAGE=`pwd`

if [ -L "$SUBLIME_PACKAGE" ];
then
    echo "Link '$SUBLIME_PACKAGE' exists. Will be unlinked"
    unlink "$SUBLIME_PACKAGE"
fi

echo "Link '$SUBLIME_PACKAGE' will be created"
ln -s "$SOURCE_PACKAGE" "$SUBLIME_PACKAGE"
