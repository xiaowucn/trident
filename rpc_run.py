#!/usr/bin/env python
# -*- coding: utf-8 -*-
# CYC: skip-file
import time
from rpc.server import serve


if __name__ == "__main__":
    print("starting server...")
    _ = serve()
    print("server started.")
    while True:
        time.sleep(100000)
