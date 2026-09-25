# -*- coding: utf-8 -*-
"""NBT 解析与聊天翻译表（从 bot.py 拆分）。"""

# 聊天翻译键 → 中文友好文本（JSON 和 NBT 组件共用）
TRANSLATE_MAP = {
    # 玩家进出
    "multiplayer.player.joined": "加入了游戏",
    "multiplayer.player.left": "离开了游戏",
    "multiplayer.player.list": "玩家列表",
    # 聊天类型
    "chat.type.text": "",
    "chat.type.emote": "",
    "chat.type.announcement": "[公告]",
    "chat.type.admin": "[管理员]",
    "chat.type.advancement.task": "达成了进度",
    "chat.type.advancement.goal": "达成了目标",
    "chat.type.advancement.challenge": "完成了挑战",
    # 命令反馈
    "commands.op.success": "已被设置为管理员",
    "commands.deop.success": "已被移出管理员",
    "commands.ban.success": "已被封禁",
    "commands.pardon.success": "已被解封",
    "commands.kick.success": "已被踢出",
    "commands.whitelist.add.success": "已加入白名单",
    "commands.whitelist.remove.success": "已移出白名单",
    "commands.gamemode.success.self": "游戏模式已更新",
    "commands.gamemode.success.other": "的游戏模式已更新",
    "commands.stop.start": "服务器正在关闭...",
    "commands.teleport.success": "已传送",
    "commands.give.success": "已给予物品",
    "commands.clear.success": "已清除物品",
    "commands.effect.success": "已添加效果",
    "commands.effect.clear.everything": "已清除所有效果",
    "commands.say": "",
    "commands.me": "",
    "commands.help.header": "--- 帮助 ---",
    # 命令错误（1.16+ 用 command. 前缀）
    "command.unknown.command": "未知命令",
    "command.unknown.server": "未知服务器",
    "command.context.here": "在这里",
    "command.context.global": "全局",
    "command.failed": "命令执行失败",
    "command.help.text": "输入 /help 查看帮助",
    # 死亡消息
    "death.attack.generic": "死了",
    "death.attack.player": "被杀死了",
    "death.attack.mob": "被怪物杀死了",
    "death.attack.fall": "摔死了",
    "death.attack.drown": "淹死了",
    "death.attack.lava": "被岩浆烧死了",
    "death.attack.fire": "被烧死了",
    "death.attack.inFire": "被火烧死了",
    "death.attack.onFire": "着火烧死了",
    "death.attack.arrow": "被箭射死了",
    "death.attack.trident": "被三叉戟扎死了",
    "death.attack.explosion": "被炸死了",
    "death.attack.void": "掉入虚空",
    "death.attack.outOfWorld": "掉出了世界",
    "death.attack.magic": "被魔法杀死了",
    "death.attack.wither": "被凋零效果杀死了",
    "death.attack.starve": "饿死了",
    "death.attack.anvil": "被铁砧砸死了",
    "death.attack.cactus": "被仙人掌扎死了",
    "death.attack.dragonBreath": "被龙息杀死了",
    "death.attack.flyIntoWall": "撞墙撞死了",
    "death.attack.thorns": "被荆棘刺死了",
    "death.attack.lightningBolt": "被闪电劈死了",
    "death.attack.cramming": "被挤死了",
    "death.attack.sweetBerryBush": "被甜浆果丛扎死了",
    "death.attack.freeze": "被冻死了",
    "death.attack.sonic_boom": "被音波杀死了",
    "death.attack.mob.projectile": "被射死了",
    "death.attack.player.projectile": "被射死了",
    "death.attack.badRespawnPoint.message": "被床炸死了",
    "death.attack.stalagmite": "被石笋戳死了",
    "death.attack.fallingBlock": "被掉落的方块砸死了",
    "death.attack.indirectMagic": "被间接魔法杀死了",
    "death.attack.fireworks": "被烟花炸死了",
    # 常见实体（entity.minecraft.xxx）
    "entity.minecraft.zombie": "僵尸",
    "entity.minecraft.skeleton": "骷髅",
    "entity.minecraft.creeper": "苦力怕",
    "entity.minecraft.spider": "蜘蛛",
    "entity.minecraft.cave_spider": "洞穴蜘蛛",
    "entity.minecraft.enderman": "末影人",
    "entity.minecraft.witch": "女巫",
    "entity.minecraft.slime": "史莱姆",
    "entity.minecraft.phantom": "幻翼",
    "entity.minecraft.blaze": "烈焰人",
    "entity.minecraft.ghast": "恶魂",
    "entity.minecraft.wither_skeleton": "凋零骷髅",
    "entity.minecraft.stray": "流浪者",
    "entity.minecraft.husk": "尸壳",
    "entity.minecraft.drowned": "溺尸",
    "entity.minecraft.zombified_piglin": "僵尸猪灵",
    "entity.minecraft.piglin": "猪灵",
    "entity.minecraft.piglin_brute": "猪灵蛮兵",
    "entity.minecraft.hoglin": "猪灵兽",
    "entity.minecraft.zoglin": "僵尸猪灵兽",
    "entity.minecraft.villager": "村民",
    "entity.minecraft.wandering_trader": "流浪商人",
    "entity.minecraft.iron_golem": "铁傀儡",
    "entity.minecraft.snow_golem": "雪傀儡",
    "entity.minecraft.wolf": "狼",
    "entity.minecraft.cat": "猫",
    "entity.minecraft.chicken": "鸡",
    "entity.minecraft.cow": "牛",
    "entity.minecraft.pig": "猪",
    "entity.minecraft.sheep": "羊",
    "entity.minecraft.horse": "马",
    "entity.minecraft.rabbit": "兔子",
    "entity.minecraft.guardian": "守卫者",
    "entity.minecraft.elder_guardian": "远古守卫者",
    "entity.minecraft.shulker": "潜影贝",
    "entity.minecraft.vindicator": "卫道士",
    "entity.minecraft.evoker": "唤魔者",
    "entity.minecraft.pillager": "掠夺者",
    "entity.minecraft.ravager": "劫掠兽",
    "entity.minecraft.vex": "恼鬼",
    "entity.minecraft.endermite": "末影螨",
    "entity.minecraft.silverfish": "蠹虫",
    "entity.minecraft.polar_bear": "北极熊",
    "entity.minecraft.panda": "熊猫",
    "entity.minecraft.fox": "狐狸",
    "entity.minecraft.bee": "蜜蜂",
    "entity.minecraft.llama": "羊驼",
    "entity.minecraft.strider": "炽足兽",
    "entity.minecraft.warden": "循声守卫",
    "entity.minecraft.allay": "悦灵",
    "entity.minecraft.goat": "山羊",
    "entity.minecraft.axolotl": "美西螈",
    "entity.minecraft.glow_squid": "发光鱿鱼",
    "entity.minecraft.squid": "鱿鱼",
    "entity.minecraft.turtle": "海龟",
    "entity.minecraft.dolphin": "海豚",
    "entity.minecraft.cod": "鳕鱼",
    "entity.minecraft.salmon": "鲑鱼",
    "entity.minecraft.pufferfish": "河豚",
    "entity.minecraft.bat": "蝙蝠",
    "entity.minecraft.ocelot": "豹猫",
    "entity.minecraft.parrot": "鹦鹉",
    "entity.minecraft.mooshroom": "哞菇",
    "entity.minecraft.wither": "凋灵",
    "entity.minecraft.ender_dragon": "末影龙",
    "entity.minecraft.giant": "巨人",
    "entity.minecraft.illusioner": "幻术师",
    # 系统
    "multiplayer.gameMode.changed": "游戏模式已更改",
    "multiplayer.disconnect.generic": "连接断开",
    "multiplayer.disconnect.kicked": "被踢出",
    "multiplayer.disconnect.banned": "被封禁",
    "multiplayer.disconnect.whitelisted": "不在白名单中",
    "multiplayer.disconnect.serverFull": "服务器已满",
    "multiplayer.disconnect.outdatedServer": "服务器版本过旧",
    "multiplayer.disconnect.outdatedClient": "客户端版本过旧",
    "chat.cannotSend": "无法发送消息",
}


def nbt_read_string(stream) -> str:
    """network NBT 字符串：2 字节大端长度 + UTF-8"""
    raw = stream.read(2)
    if len(raw) < 2:
        return ""
    slen = int.from_bytes(raw, "big")
    return stream.read(slen).decode("utf-8", "ignore")


def nbt_skip_value(stream, tag: int):
    """跳过未知 NBT 值"""
    if tag == 0x01:  # byte
        stream.read(1)
    elif tag == 0x02:  # short
        stream.read(2)
    elif tag in (0x03, 0x05, 0x06):  # int / float / double
        stream.read(4) if tag in (0x03, 0x05) else stream.read(8)
    elif tag == 0x04:  # long
        stream.read(8)
    elif tag == 0x07:  # byte array
        stream.read(int.from_bytes(stream.read(4), "big"))
    elif tag == 0x08:  # string
        nbt_read_string(stream)
    elif tag == 0x09:  # list
        elem = stream.read(1)
        if not elem:
            return
        count = int.from_bytes(stream.read(4), "big")
        for _ in range(count):
            nbt_skip_value(stream, elem[0])
    elif tag == 0x0a:  # compound
        nbt_compound_to_text(stream)
    elif tag == 0x0b:  # int array
        stream.read(4 * int.from_bytes(stream.read(4), "big"))
    elif tag == 0x0c:  # long array
        stream.read(8 * int.from_bytes(stream.read(4), "big"))


def nbt_compound_to_text(stream) -> str:
    """解析 network NBT 聊天组件（TAG_Compound），提取可读文本"""
    text_val = ""
    translate_key = ""
    with_parts = []
    extra_parts = []
    while True:
        raw = stream.read(1)
        if not raw:
            break
        tag = raw[0]
        if tag == 0x00:  # TAG_End
            break
        name = nbt_read_string(stream)
        if tag == 0x08:  # TAG_String
            val = nbt_read_string(stream)
            if name == "text":
                text_val = val
            elif name == "translate":
                translate_key = val
        elif tag == 0x09:  # TAG_List（with / extra）
            elem_type_raw = stream.read(1)
            if not elem_type_raw:
                break
            elem_type = elem_type_raw[0]
            count = int.from_bytes(stream.read(4), "big")
            items = []
            for _ in range(count):
                if elem_type == 0x0a:
                    items.append(nbt_compound_to_text(stream))
                elif elem_type == 0x08:
                    items.append(nbt_read_string(stream))
                else:
                    nbt_skip_value(stream, elem_type)
            if name == "with":
                with_parts = items
            elif name == "extra":
                extra_parts = items
        elif tag == 0x0a:  # 嵌套 compound（hoverEvent 等，跳过）
            nbt_compound_to_text(stream)
        else:
            nbt_skip_value(stream, tag)
    if translate_key:
        friendly = TRANSLATE_MAP.get(translate_key)
        # 成就类消息：with = [玩家名, 成就名]，格式化为 "玩家名 达成了目标 [成就名]"
        if translate_key.startswith("chat.type.advancement") and len(with_parts) >= 2:
            player = with_parts[0]
            adv = with_parts[1]
            if friendly:
                return f"{player} {friendly} [{adv}]"
            return f"{player} {translate_key} [{adv}]"
        # 死亡类消息：with = [玩家名, 凶手]，如 "WatchDog123 被怪物杀死了 (僵尸)"（与 JSON 版格式对齐）
        if translate_key.startswith("death.attack") and len(with_parts) >= 2:
            player = with_parts[0]
            killer = with_parts[1]
            if friendly:
                return f"{player} {friendly} ({killer})" if killer else f"{player} {friendly}"
            return f"{player} {translate_key} ({killer})" if killer else f"{player} {translate_key}"
        prefix = " ".join(part for part in with_parts if part)
        if friendly is not None:
            if prefix:
                return prefix + (" " + friendly if friendly else "")
            return friendly
        if prefix:
            return prefix + " " + translate_key
        return translate_key
    return text_val + "".join(extra_parts)


def nbt_component_to_text(stream) -> str:
    """解析 network NBT 聊天组件（根节点可能为 Compound 或 String）"""
    raw = stream.read(1)
    if not raw:
        return ""
    tag = raw[0]
    if tag == 0x0a:  # TAG_Compound
        return nbt_compound_to_text(stream)
    if tag == 0x08:  # TAG_String（纯文本组件）
        return nbt_read_string(stream)
    if tag == 0x00:  # TAG_End
        return ""
    nbt_skip_value(stream, tag)
    return ""
