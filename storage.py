# -*- coding: utf-8 -*-
"""账号数据本地存储。

API Key 使用 Windows DPAPI（当前 Windows 用户绑定）加密后落盘，
避免以明文形式保存在配置文件里。
"""

import base64
import ctypes
import json
import os
import time
import uuid


APP_DIR = os.path.join(os.path.expanduser("~"), ".model_balance")
CONFIG_PATH = os.path.join(APP_DIR, "accounts.json")
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_protect(data):
    """用 Windows DPAPI 加密 bytes，返回 bytes。"""
    blob_in = _DataBlob(len(data), ctypes.create_string_buffer(data))
    blob_out = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise RuntimeError("Windows 加密失败")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(data):
    """用 Windows DPAPI 解密 bytes，返回 bytes。"""
    blob_in = _DataBlob(len(data), ctypes.create_string_buffer(data))
    blob_out = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise RuntimeError("Windows 解密失败")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _encrypt(plain):
    return base64.b64encode(_dpapi_protect(plain.encode("utf-8"))).decode("ascii")


def _decrypt(token):
    return _dpapi_unprotect(base64.b64decode(token)).decode("utf-8")


def new_id():
    return uuid.uuid4().hex


def load_accounts():
    """读取本地账号列表。文件不存在或损坏时返回空列表。"""
    if not os.path.exists(CONFIG_PATH):
        return []
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        accounts = []
        for item in raw:
            try:
                api_key = _decrypt(item["api_key_enc"])
            except Exception:  # noqa: BLE001
                api_key = item.get("api_key", "")
            accounts.append({
                "id": item.get("id") or new_id(),
                "name": item.get("name", ""),
                "provider": item.get("provider", ""),
                "api_key": api_key,
                "base_url": item.get("base_url") or "",
                "created_at": item.get("created_at"),
            })
        return accounts
    except Exception:  # noqa: BLE001
        return []


def save_accounts(accounts):
    """把账号列表写入本地文件，API Key 加密存储。"""
    os.makedirs(APP_DIR, exist_ok=True)
    payload = []
    for a in accounts:
        try:
            enc = _encrypt(a["api_key"])
        except Exception:  # noqa: BLE001
            enc = ""
        payload.append({
            "id": a.get("id") or new_id(),
            "name": a.get("name", ""),
            "provider": a.get("provider", ""),
            "api_key_enc": enc,
            "base_url": a.get("base_url") or "",
            "created_at": a.get("created_at") or time.time(),
        })
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_settings():
    """读取本地设置（如自动刷新）。文件缺失或损坏时返回默认值。"""
    defaults = {"auto_refresh": False, "auto_minutes": 10,
                "auto_sync": False, "auto_sync_minutes": 30,
                "master_account_id": "", "master_api_name": "",
                "alerts": {}, "sort_mode": ""}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k in defaults:
                if k in data:
                    defaults[k] = data[k]
    except Exception:  # noqa: BLE001
        pass
    return defaults


def save_settings(settings):
    """把设置写入本地文件，下次启动时生效。"""
    os.makedirs(APP_DIR, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
