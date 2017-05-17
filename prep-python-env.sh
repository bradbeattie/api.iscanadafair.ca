#!/bin/bash
DIR=$(pwd)

# Download Python
PYTHON_VERSION="3.6.1"
PYTHON_VERSION_SHORT="3.6"
PYTHON_DOWNLOAD_URL="https://www.python.org/ftp/python/$PYTHON_VERSION/Python-$PYTHON_VERSION.tgz"
PYTHON_DOWNLOAD_FILE="Python-$PYTHON_VERSION.tgz"
curl $PYTHON_DOWNLOAD_URL > $PYTHON_DOWNLOAD_FILE
PYTHON_MD5SUM_EXPECTED="2d0fc9f3a5940707590e07f03ecb08b9"
PYTHON_MD5SUM_ACTUAL=$(md5sum $PYTHON_DOWNLOAD_FILE | cut -d" " -f1)
if [ $PYTHON_MD5SUM_ACTUAL != $PYTHON_MD5SUM_EXPECTED ]; then
    echo "$PYTHON_DOWNLOAD_URL md5sum mismatch"
    rm $PYTHON_DOWNLOAD_FILE
    exit 1
fi
tar xfz $PYTHON_DOWNLOAD_FILE
rm $PYTHON_DOWNLOAD_FILE

# Compile Python
cd Python-$PYTHON_VERSION
mkdir dist
./configure --enable-shared --prefix $DIR/Python-$PYTHON_VERSION/dist LDFLAGS=-Wl,-rpath=$DIR/Python-$PYTHON_VERSION/dist/lib && make -j && make install
cd ..

# Create and activate the virtualenv environment
Python-$PYTHON_VERSION/dist/bin/python$PYTHON_VERSION_SHORT -m venv .env-$PYTHON_VERSION