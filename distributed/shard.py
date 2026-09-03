# -*- coding: utf-8 -*-
"""
分布式任务分片（v3.2.1 新增，融合 matscan 特性）。
将大网段扫描任务分割为多个分片，分配给多个 worker 节点并行执行。
基于文件的简单分片管理（不依赖 Redis/Zookeeper，与原版轻量风格一致）。
"""
import hashlib
import ipaddress
import json
import os


def shard_cidr(cidr: str, num_shards: int, ports: list = None) -> list:
    """
    将 CIDR 网段分割为多个分片。
    返回: [{"shard_id": 0, "targets": "1.0.0.0/24", "ports": [25565], "estimated_hosts": N}, ...]
    """
    if ports is None:
        ports = [25565]

    net = ipaddress.ip_network(cidr, strict=False)
    total_hosts = net.num_addresses

    if total_hosts <= num_shards:
        shards = []
        for i, addr in enumerate(net.hosts()):
            shards.append({
                "shard_id": i,
                "targets": str(addr),
                "ports": ports,
                "estimated_hosts": 1,
            })
        return shards

    # 按前缀长度分割
    prefix_len = net.prefixlen
    new_prefix = prefix_len
    while (2 ** (new_prefix - prefix_len)) < num_shards and new_prefix < 32:
        new_prefix += 1

    subnets = list(net.subnets(new_prefix=new_prefix))
    per_shard = max(1, len(subnets) // num_shards)
    shards = []
    for i in range(0, len(subnets), per_shard):
        group = subnets[i:i + per_shard]
        if not group:
            break
        shard_id = len(shards)
        if len(group) == 1:
            target = str(group[0])
        else:
            target = f"{group[0].network_address}-{group[-1].broadcast_address}"
        shards.append({
            "shard_id": shard_id,
            "targets": target,
            "ports": ports,
            "estimated_hosts": sum(s.num_addresses for s in group),
            "subnets": [str(s) for s in group],
        })
        if len(shards) >= num_shards:
            break
    return shards


def shard_target_file(filepath: str, num_shards: int, ports: list = None) -> list:
    """
    将目标文件中的目标分配到多个分片（一致性哈希）。
    """
    if ports is None:
        ports = [25565]

    targets = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    targets.append(line)
    except FileNotFoundError:
        return []

    shards = [{"shard_id": i, "targets": [], "ports": ports, "estimated_hosts": 0}
              for i in range(num_shards)]

    for target in targets:
        h = int(hashlib.md5(target.encode()).hexdigest(), 16)
        shard_id = h % num_shards
        shards[shard_id]["targets"].append(target)
        shards[shard_id]["estimated_hosts"] += 1

    return [s for s in shards if s["targets"]]


class ShardManager:
    """分片管理器：分配、领取、完成分片任务（基于文件状态）。"""

    def __init__(self, state_dir: str = "shards"):
        self.state_dir = state_dir
        os.makedirs(state_dir, exist_ok=True)

    def create_job(self, job_id: str, targets: str, num_shards: int,
                    ports: list = None) -> list:
        """创建一个扫描任务，生成分片。"""
        if "/" in targets:
            shards = shard_cidr(targets, num_shards, ports)
        elif os.path.exists(targets):
            shards = shard_target_file(targets, num_shards, ports)
        else:
            shards = [{"shard_id": 0, "targets": targets, "ports": ports or [25565], "estimated_hosts": 1}]

        job = {
            "job_id": job_id,
            "total_shards": len(shards),
            "completed_shards": 0,
            "shards": {str(s["shard_id"]): {**s, "status": "pending", "worker": None, "completed_at": None}
                        for s in shards},
        }
        self._save_job(job_id, job)
        return shards

    def claim_shard(self, job_id: str, worker_id: str) -> dict:
        """Worker 领取一个待处理的分片。"""
        job = self._load_job(job_id)
        if not job:
            return None
        for sid, shard in job["shards"].items():
            if shard["status"] == "pending":
                shard["status"] = "running"
                shard["worker"] = worker_id
                self._save_job(job_id, job)
                return shard
        return None

    def complete_shard(self, job_id: str, shard_id: int, result_summary: dict):
        """标记分片完成。"""
        job = self._load_job(job_id)
        if not job:
            return
        sid = str(shard_id)
        if sid in job["shards"]:
            job["shards"][sid]["status"] = "completed"
            job["shards"][sid]["result"] = result_summary
            job["completed_shards"] += 1
            self._save_job(job_id, job)

    def get_job_status(self, job_id: str) -> dict:
        """获取任务状态。"""
        job = self._load_job(job_id)
        if not job:
            return {}
        return {
            "job_id": job_id,
            "total_shards": job["total_shards"],
            "completed_shards": job["completed_shards"],
            "progress": round(job["completed_shards"] / job["total_shards"] * 100, 1) if job["total_shards"] else 0,
            "shards": {k: {"status": v["status"], "worker": v.get("worker")}
                        for k, v in job["shards"].items()},
        }

    def _save_job(self, job_id: str, job: dict):
        path = os.path.join(self.state_dir, f"{job_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False, indent=2)

    def _load_job(self, job_id: str) -> dict:
        path = os.path.join(self.state_dir, f"{job_id}.json")
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
