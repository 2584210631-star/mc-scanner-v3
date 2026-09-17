# -*- coding: utf-8 -*-
"""Routes: AI generate/send"""
from flask import request, jsonify
import time
import config, logger
try:
    from web import state
except ImportError:
    import state  # type: ignore

def register(app):
    @app.route('/api/ai/presets')
    def ai_presets():
        from core.ai_generator import get_preset_list
        return jsonify({"presets": get_preset_list()})

    @app.route('/api/ai/get')
    def ai_get():
        return jsonify({
            "api_key": "***" if config.get("ai_api_key") else "",
            "base_url": config.get("ai_base_url", ""),
            "model": config.get("ai_model", ""),
        })

    @app.route('/api/ai/generate', methods=['POST'])
    def ai_generate():
        data = request.json or {}
        from core.ai_generator import generate_content
        result = generate_content(
            topic=data.get("topic", ""),
            preset=data.get("preset", "custom"),
            api_key=data.get("api_key") or config.get("ai_api_key", ""),
            base_url=data.get("base_url") or config.get("ai_base_url", ""),
            model=data.get("model") or config.get("ai_model", ""),
            custom_prompt=data.get("custom_prompt"),
        )
        return jsonify(result)

    @app.route('/api/ai/send', methods=['POST'])
    def ai_send():
        data = request.json or {}
        from core.ai_generator import generate_content, split_for_minecraft
        from core.bot import MCBot
        result = generate_content(
            topic=data.get("topic", ""),
            preset=data.get("preset", "custom"),
            api_key=data.get("api_key") or config.get("ai_api_key", ""),
            base_url=data.get("base_url") or config.get("ai_base_url", ""),
            model=data.get("model") or config.get("ai_model", ""),
            custom_prompt=data.get("custom_prompt"),
        )
        if not result.get("success"):
            return jsonify(result)
        host = data.get("host")
        port = int(data.get("port", 25565))
        username = data.get("username", "AIBot")
        try:
            bot = MCBot(host=host, port=port, username=username, timeout=20)
            bot.connect()
            for line in split_for_minecraft(result.get("text", "")):
                bot.send_chat(line)
                time.sleep(0.5)
            bot.close()
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)[:200]})
