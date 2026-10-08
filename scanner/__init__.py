# MC Scanner v3-3.1 - scanner 扫描引擎层
"""扫描引擎层：端口扫描 / SLP 探测 / 目标解析 / 安全策略。

历史实现只有一行注释，导入接口不明确。这里用 PEP 562 惰性导出：
既给出显式接口（__all__），又不会在 import scanner 时就把 core/storage
整条链路拉起来（那会显著增加导入耗时并可能引入循环导入）。
"""

__all__ = [
    # 引擎
    "ScanEngine", "AsyncScanEngine", "run_async_scan",
    # 端口扫描
    "ScanResult", "AsyncScanResult", "check_port", "scan_ports", "get_open_ports",
    "scan_ports_async", "scan_ports_coro", "scan_ports_blocking",
    "get_open_ports_async", "has_uvloop",
    # SLP / 探测
    "async_slp_probe", "async_auth_probe",
    # 目标解析
    "parse_targets", "count_targets", "parse_port_spec", "deduplicate_targets",
    "MAX_TARGETS",
    # 排除表 / 重复检测 / 重扫
    "Excluder", "DuplicateDetector", "RescanScheduler",
    # 安全策略
    "ScanProfile", "get_profile", "ScanProgressStore", "AdaptiveRateController",
    "shuffle_targets", "iter_shuffled_chunks",
    # masscan / 随机扫描
    "has_masscan", "run_masscan", "parse_masscan_json",
    "random_scan", "async_random_scan", "parse_port_ranges",
    # 抽象基类
    "BaseScanner", "get_scanner",
]

# 公开名 -> (模块, 属性名)
_EXPORTS = {
    "ScanEngine": ("scanner.engine", "ScanEngine"),
    "AsyncScanEngine": ("scanner.async_engine", "AsyncScanEngine"),
    "run_async_scan": ("scanner.async_engine", "run_async_scan"),
    "ScanResult": ("scanner.portscan", "ScanResult"),
    "check_port": ("scanner.portscan", "check_port"),
    "scan_ports": ("scanner.portscan", "scan_ports"),
    "get_open_ports": ("scanner.portscan", "get_open_ports"),
    "AsyncScanResult": ("scanner.async_portscan", "AsyncScanResult"),
    "scan_ports_async": ("scanner.async_portscan", "scan_ports_async"),
    "scan_ports_coro": ("scanner.async_portscan", "scan_ports_coro"),
    "scan_ports_blocking": ("scanner.async_portscan", "scan_ports_blocking"),
    "get_open_ports_async": ("scanner.async_portscan", "get_open_ports_async"),
    "has_uvloop": ("scanner.async_portscan", "has_uvloop"),
    "async_slp_probe": ("scanner.async_probe", "async_slp_probe"),
    "async_auth_probe": ("scanner.async_probe", "async_auth_probe"),
    "parse_targets": ("scanner.targets", "parse_targets"),
    "count_targets": ("scanner.targets", "count_targets"),
    "parse_port_spec": ("scanner.targets", "parse_port_spec"),
    "deduplicate_targets": ("scanner.targets", "deduplicate_targets"),
    "MAX_TARGETS": ("scanner.targets", "MAX_TARGETS"),
    "Excluder": ("scanner.exclude", "Excluder"),
    "DuplicateDetector": ("scanner.duplicate", "DuplicateDetector"),
    "RescanScheduler": ("scanner.rescanner", "RescanScheduler"),
    "ScanProfile": ("scanner.safe", "ScanProfile"),
    "get_profile": ("scanner.safe", "get_profile"),
    "ScanProgressStore": ("scanner.safe", "ScanProgressStore"),
    "AdaptiveRateController": ("scanner.safe", "AdaptiveRateController"),
    "shuffle_targets": ("scanner.safe", "shuffle_targets"),
    "iter_shuffled_chunks": ("scanner.safe", "iter_shuffled_chunks"),
    "has_masscan": ("scanner.masscan", "has_masscan"),
    "run_masscan": ("scanner.masscan", "run_masscan"),
    "parse_masscan_json": ("scanner.masscan", "parse_masscan_json"),
    "random_scan": ("scanner.random_scan", "random_scan"),
    "async_random_scan": ("scanner.random_scan", "async_random_scan"),
    "parse_port_ranges": ("scanner.random_scan", "parse_port_ranges"),
    "BaseScanner": ("scanner.base", "BaseScanner"),
    "get_scanner": ("scanner.base", "get_scanner"),
}


def __getattr__(name):
    target = _EXPORTS.get(name)
    if target is not None:
        import importlib
        value = getattr(importlib.import_module(target[0]), target[1])
        globals()[name] = value
        return value
    if name.startswith("_"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    # 兼容 scanner.<子模块> 的属性访问（PEP 562 下不会自动生成子模块属性）
    import importlib
    try:
        module = importlib.import_module(f"{__name__}.{name}")
    except ImportError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = module
    return module
