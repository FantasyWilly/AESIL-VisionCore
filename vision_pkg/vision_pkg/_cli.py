#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse

# ------------------------------------------------------------------------------------ #
# CLI 說明格式
# ------------------------------------------------------------------------------------ #
class CLIHelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawDescriptionHelpFormatter,
):
    """保留說明文字排版並自動顯示參數預設值"""