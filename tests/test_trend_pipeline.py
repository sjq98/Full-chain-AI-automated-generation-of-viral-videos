import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class TrendPipelineTests(unittest.TestCase):
    def test_discovery_worker_persists_percent_progress(self):
        app.TREND_TASKS = {}
        with patch.object(app, "discover_ai_trends", return_value={
            "search_id": "trend-test",
            "requested_count": 3,
            "topics": [{"title": "A"}],
            "candidates": [{"title": "video"}],
        }) as discover:
            task = app.start_trend_discovery({"limit": 3})
            worker = app.TREND_TASKS[task["task_id"]]
            # The worker is intentionally asynchronous; wait briefly for the
            # deterministic mocked worker to finish before checking its state.
            for _ in range(20):
                if app.TREND_TASKS[task["task_id"]].get("status") == "done":
                    break
                import time
                time.sleep(0.01)

        finished = app.TREND_TASKS[task["task_id"]]
        self.assertTrue(discover.called)
        self.assertEqual(finished["status"], "done")
        self.assertEqual(finished["percent"], 100)
        self.assertEqual(finished["topic_count"], 1)

    def test_duplicate_discovery_reuses_the_active_task(self):
        app.TREND_TASKS = {}
        app.ACTIVE_TREND_DISCOVERY_TASK_ID = None
        with patch.object(app.threading, "Thread") as thread:
            first = app.start_trend_discovery({"limit": 3})
            second = app.start_trend_discovery({"limit": 3})

        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual(thread.call_count, 1)

    def test_hotspot_pool_worker_reports_progress_and_returns_pool(self):
        app.TREND_TASKS = {}
        app.ACTIVE_TREND_HOTSPOT_TASK_ID = None
        pool = {
            "pool_id": "hotspots-test",
            "source_count": 2,
            "hotspots": [{"hotspot_id": "hotspot-001", "title": "测试热点"}],
        }

        def fake_build(*_args, progress_callback=None, **_kwargs):
            progress_callback(0.28, "已获取 2 条 36Kr 报道")
            progress_callback(0.78, "AI 已返回拆分结果")
            return pool

        with patch.object(app, "build_trend_hotspot_pool", side_effect=fake_build):
            task = app.start_trend_hotspot_pool_build({"start_at": "2026-08-25"})
            for _ in range(20):
                if app.TREND_TASKS[task["task_id"]].get("status") == "done":
                    break
                import time
                time.sleep(0.01)

        finished = app.TREND_TASKS[task["task_id"]]
        self.assertEqual(finished["status"], "done")
        self.assertEqual(finished["percent"], 100)
        self.assertEqual(finished["progress_label"], "热点拆分进度")
        self.assertEqual(finished["pool"], pool)

    def test_knowledge_is_saved_when_llm_is_unavailable(self):
        with patch.object(app, "llm_json", side_effect=RuntimeError("mock network unavailable")):
            entry = app.structure_trend_knowledge(
                "我偏好企业家对科技趋势给出明确时间判断的访谈，不要泛泛鸡汤。"
            )

        self.assertEqual(entry["structure_source"], "fallback")
        self.assertEqual(entry["structure_warning"], "mock network unavailable")
        self.assertEqual(entry["themes"], [])
        self.assertTrue(entry["raw_note"])

    def test_discovery_pipeline_returns_ranked_topics_and_materials(self):
        def fake_llm(prompt, **_kwargs):
            return {
                "topics": [
                    {
                        "person_id": "person-001",
                        "source_id": "source_001",
                        "title": "王兴兴：人形机器人关键突破窗口",
                        "category": "科技判断",
                        "speaker_name": "王兴兴",
                        "speaker_role": "宇树科技创始人",
                        "statement_summary": "围绕人形机器人的技术进展给出公开判断。",
                        "heat_reason": "人物、技术趋势和明确时间判断兼具。",
                        "evidence_excerpt": "在公开活动中谈到人形机器人的技术进展。",
                        "source_confidence": "high",
                        "material_queries": ["王兴兴 人形机器人 采访"],
                        "recommendation_reason": "符合科技趋势加企业家判断的偏好。",
                    },
                    {
                        "person_id": "person-002",
                        "source_id": "source_002",
                        "title": "李想：智能汽车竞争判断",
                        "category": "商业趋势",
                        "speaker_name": "李想",
                        "speaker_role": "理想汽车创始人",
                        "statement_summary": "围绕行业竞争与产品节奏给出判断。",
                        "heat_reason": "行业竞争话题有明确人物来源。",
                        "evidence_excerpt": "在访谈中分享对行业竞争与产品节奏的判断。",
                        "source_confidence": "high",
                        "material_queries": ["李想 智能汽车 访谈"],
                        "recommendation_reason": "符合企业家访谈偏好。",
                    },
                    {
                        "person_id": "person-003",
                        "source_id": "source_003",
                        "title": "周鸿祎：AI Agent 商业化",
                        "category": "商业趋势",
                        "speaker_name": "周鸿祎",
                        "speaker_role": "360 创始人",
                        "statement_summary": "讨论 AI Agent 的商业化方向。",
                        "heat_reason": "AI 商业化讨论具备时效性。",
                        "evidence_excerpt": "在演讲中讨论 AI Agent 的商业化方向。",
                        "source_confidence": "medium",
                        "material_queries": ["周鸿祎 AI Agent 演讲"],
                        "recommendation_reason": "符合科技商业主题偏好。",
                    },
                ]
            }

        source_specs = [
            ("person-001", "王兴兴", "王兴兴谈人形机器人关键突破", "宇树科技创始人王兴兴在公开活动中谈到人形机器人的技术进展。", 84),
            ("person-002", "李想", "李想分享智能汽车竞争判断", "理想汽车创始人李想在访谈中分享对行业竞争与产品节奏的判断。", 80),
            ("person-003", "周鸿祎", "周鸿祎谈 AI Agent 商业化", "360 创始人周鸿祎在演讲中讨论 AI Agent 的商业化方向。", 78),
        ]
        people = []
        for index, (person_id, name, title, description, heat_score) in enumerate(source_specs, start=1):
            people.append({
                "person_id": person_id,
                "name": name,
                "source_count": 1,
                "heat_score": heat_score,
                "sources": [{
                    "title": title,
                    "url": f"https://36kr.com/p/{index}",
                    "description": description,
                    "published_at": "2026-08-21",
                    "heat_score": heat_score,
                    "source_name": "36Kr",
                }],
            })

        def fake_crawler(keywords, platform, _limit, *_args):
            candidates = []
            for index, keyword in enumerate(keywords, start=1):
                speaker = keyword.split()[0]
                candidates.append({
                    "candidate_id": f"candidate-{index}",
                    "title": f"{speaker} 公开访谈完整视频",
                    "description": "公开访谈现场，保留原始发言上下文。",
                    "url": f"https://example.test/{platform}/{index}",
                    "platform": app.media_crawler_platform_label(platform),
                    "author": "权威媒体",
                    "published_at": "2026-08-21",
                    "keyword": keyword,
                    "heat_score": 74,
                })
            return keywords, candidates, []

        knowledge = [{"主题": "科技趋势", "偏好人物": ["企业家"], "喜欢信号": ["明确判断"]}]
        with tempfile.TemporaryDirectory() as directory:
            result_path = Path(directory) / "result.json"
            pool_path = Path(directory) / "people.json"
            pool_path.write_text(json.dumps({"pool_id": "people-test", "people": people, "warnings": []}, ensure_ascii=False), encoding="utf-8")
            with (
                patch.object(app, "trend_knowledge_context", return_value=knowledge),
                patch.object(app, "llm_json", side_effect=fake_llm),
                patch.object(app, "fetch_hot_topic_sources", side_effect=AssertionError("stage two must not fetch 36Kr again")),
                patch.object(app, "search_media_crawler_candidates", side_effect=fake_crawler),
                patch.object(app, "trend_search_path", return_value=result_path),
                patch.object(app, "trend_person_pool_path", return_value=pool_path),
            ):
                result = app.discover_ai_trends({"person_pool_id": "people-test", "person_ids": [item["person_id"] for item in people], "platforms": ["bili", "dy"]})

            self.assertEqual(len(result["topics"]), 3)
            self.assertEqual(result["knowledge_count"], 1)
            self.assertEqual(len(result["generated_queries"]), 3)
            self.assertEqual(result["requested_count"], 3)
            self.assertEqual(result["provider"], "视频素材搜索")
            self.assertTrue(all(topic["source_name"] == "36Kr" for topic in result["topics"]))
            self.assertTrue(all(topic["materials"] for topic in result["topics"]))
            self.assertTrue(all(material["source_grade"] in {"A", "B", "C"} for material in result["candidates"]))
            self.assertTrue(result_path.exists())

    def test_selected_people_are_kept_when_material_is_missing(self):
        sources = [
            {"title": f"36Kr 热点 {index}", "url": f"https://36kr.com/p/{index}", "description": f"人物 {index} 公开发言", "published_at": "2026-08-24", "heat_score": 80, "source_name": "36Kr"}
            for index in range(1, 4)
        ]
        names = ["人物1", "人物2", "人物3"]
        selected = []
        for index, source in enumerate(sources, start=1):
            selected.append({
                "topic_id": f"topic-{index}", "person_id": f"person-{index:03d}", "title": source["title"], "speaker_name": f"人物{index}",
                "speaker_role": "创始人", "statement_summary": "公开观点", "heat_reason": "热点", "evidence_excerpt": "证据",
                "source_confidence": "high", "source_title": source["title"], "source_url": source["url"], "source_name": "36Kr",
                "published_at": "2026-08-24", "material_queries": [f"人物{index} 访谈", f"人物{index} 演讲"], "recommendation_reason": "匹配", "materials": [],
            })

        def fake_crawler(keywords, platform, _limit, *_args):
            candidates = []
            for query in keywords:
                if query.startswith("人物1"):
                    continue
                speaker = query.split()[0]
                candidates.append({"candidate_id": query, "title": f"{speaker} 完整访谈", "description": "公开访谈", "url": f"https://video.test/{platform}/{speaker}", "platform": platform, "author": "媒体", "published_at": "2026-08-24", "keyword": query, "heat_score": 70})
            return keywords, candidates, []

        with tempfile.TemporaryDirectory() as directory:
            result_path = Path(directory) / "result.json"
            pool_path = Path(directory) / "people.json"
            people = [{"person_id": f"person-{index:03d}", "name": name, "sources": [sources[index - 1]]} for index, name in enumerate(names, start=1)]
            pool_path.write_text(json.dumps({"pool_id": "people-test", "people": people, "warnings": []}, ensure_ascii=False), encoding="utf-8")
            with (
                patch.object(app, "trend_knowledge_context", return_value=[{"主题": "商业"}]),
                patch.object(app, "choose_trend_topics", return_value=selected),
                patch.object(app, "search_media_crawler_candidates", side_effect=fake_crawler),
                patch.object(app, "trend_search_path", return_value=result_path),
                patch.object(app, "trend_person_pool_path", return_value=pool_path),
            ):
                result = app.discover_ai_trends({"person_pool_id": "people-test", "person_ids": [item["person_id"] for item in people], "platforms": ["bili"]})

        self.assertEqual(len(result["topics"]), 3)
        self.assertIn("人物1", [topic["speaker_name"] for topic in result["topics"]])
        self.assertFalse(result["topics"][0]["materials"])
        self.assertTrue(all(topic["materials"] for topic in result["topics"][1:]))

    def test_hotspot_date_filters_historical_source_footage(self):
        source = {"title": "36Kr 热点", "url": "https://36kr.com/p/1", "description": "人物公开发言", "published_at": "2026-08-24", "heat_score": 80}
        topic = {
            "topic_id": "topic-1", "title": "热点选题", "speaker_name": "人物甲", "speaker_role": "创始人",
            "statement_summary": "公开观点", "heat_reason": "热点", "evidence_excerpt": "证据",
            "source_confidence": "high", "source_title": source["title"], "source_url": source["url"],
            "source_name": "36Kr", "published_at": source["published_at"], "material_queries": ["人物甲 访谈"],
            "recommendation_reason": "匹配", "materials": [],
        }
        received_ranges = []

        def fake_crawler(keywords, platform, _limit, start_at, end_at, min_published_at):
            received_ranges.append((start_at, end_at, min_published_at))
            return keywords, [{
                "candidate_id": "history-video", "title": "人物甲 完整访谈", "description": "公开对话",
                "url": "https://video.test/history", "platform": platform, "author": "媒体",
                "published_at": "2025-08-24", "keyword": keywords[0], "heat_score": 70,
            }], []

        with tempfile.TemporaryDirectory() as directory:
            result_path = Path(directory) / "result.json"
            pool_path = Path(directory) / "people.json"
            people = [{"person_id": "person-001", "name": "人物甲", "sources": [source]}]
            pool_path.write_text(json.dumps({"pool_id": "people-test", "people": people, "warnings": []}, ensure_ascii=False), encoding="utf-8")
            with (
                patch.object(app, "trend_knowledge_context", return_value=[{"主题": "商业"}]),
                patch.object(app, "choose_trend_topics", return_value=[topic]),
                patch.object(app, "search_media_crawler_candidates", side_effect=fake_crawler),
                patch.object(app, "trend_search_path", return_value=result_path),
                patch.object(app, "trend_person_pool_path", return_value=pool_path),
            ):
                result = app.discover_ai_trends({"person_pool_id": "people-test", "person_ids": ["person-001"], "platforms": ["bili"], "start_at": "2026-08-24", "end_at": "2026-08-24"})

        self.assertEqual(received_ranges, [("", "", "2026-08-24"), ("", "", "2026-08-24")])
        self.assertEqual(len(result["topics"]), 1)
        self.assertFalse(result["topics"][0]["materials"])
        self.assertTrue(any("早于热点报道发布时间" in warning for warning in result["warnings"]))

    def test_hotspot_timestamp_filters_earlier_same_day_video(self):
        # Hotspot filtering intentionally ignores the time of day.
        self.assertFalse(app.is_published_before("2026-08-24 08:59:59", "2026-08-24 09:00:00"))
        self.assertFalse(app.is_published_before("2026-08-24 09:00:00", "2026-08-24 09:00:00"))
        self.assertFalse(app.is_published_before("2026-08-24 09:00:01", "2026-08-24 09:00:00"))
        self.assertTrue(app.is_published_before("2026-08-23 23:59:59", "2026-08-24 00:00:00"))

    def test_trend_platforms_add_douyin_as_bilibili_fallback(self):
        self.assertEqual(app.normalize_trend_platforms(["bili"]), ["bili", "dy"])
        self.assertEqual(app.normalize_trend_platforms(["dy"]), ["dy"])
        self.assertEqual(app.normalize_trend_platforms([]), ["bili", "dy"])

    def test_unix_video_timestamp_is_compared_by_local_date(self):
        self.assertEqual(app.parse_result_date("1761296205").isoformat(), "2025-10-24")
        self.assertTrue(app.is_published_before("1761296205", "2026-08-20 15:38:36"))

    def test_final_material_pass_removes_stale_historical_candidates(self):
        topics = [{
            "topic_id": "topic-1",
            "title": "热点",
            "published_at": "2026-08-20 15:38:36",
            "materials": [
                {"url": "https://video.test/old", "published_at": "1761296205", "material_score": 99},
                {"url": "https://video.test/current", "published_at": "2026-08-20 08:00:00", "material_score": 80},
            ],
        }]
        discarded = app.enforce_topic_material_date_cutoff(topics, material_limit=3)
        self.assertEqual(discarded, 1)
        self.assertEqual([item["url"] for item in topics[0]["materials"]], ["https://video.test/current"])

    def test_material_lookup_runs_per_person_and_stops_after_target(self):
        topics = [
            {"topic_id": "topic-1", "title": "A", "speaker_name": "人物甲", "materials": [], "material_queries": ["人物甲 访谈"]},
            {"topic_id": "topic-2", "title": "B", "speaker_name": "人物乙", "materials": [], "material_queries": ["人物乙 访谈"]},
        ]
        seen_keywords = []

        def fake_crawler(keywords, platform, _limit, *_args):
            seen_keywords.append(list(keywords))
            person = keywords[0].split()[0]
            return keywords, [{
                "candidate_id": person, "title": f"{person} 完整访谈", "description": "公开对话",
                "url": f"https://video.test/{person}", "platform": platform, "author": "媒体",
                "published_at": "2025-08-24", "keyword": keywords[0], "heat_score": 70,
            }], []

        with patch.object(app, "search_media_crawler_candidates", side_effect=fake_crawler):
            app.collect_trend_materials(topics, ["bili"], material_limit=3, target_count=1)

        self.assertEqual(seen_keywords, [["人物甲 访谈"]])
        self.assertTrue(topics[0]["materials"])
        self.assertFalse(topics[1]["materials"])

    def test_material_lookup_falls_back_to_douyin_when_bilibili_is_short(self):
        topics = [{
            "topic_id": "topic-1",
            "title": "热点",
            "subject_label": "目标主体",
            "match_terms": ["目标主体"],
            "published_at": "2026-08-20",
            "materials": [],
            "material_queries": ["目标主体 事件", "目标主体 发布会"],
        }]
        calls = []

        def fake_crawler(keywords, platform, _limit, *_args):
            calls.append(platform)
            count = 1 if platform == "bili" else 2
            candidates = [{
                "candidate_id": f"{platform}-{index}",
                "title": f"目标主体 {platform} 视频 {index}",
                "description": "事件现场",
                "url": f"https://video.test/{platform}/{index}",
                "platform": platform,
                "author": "媒体",
                "published_at": "2026-08-21",
                "keyword": keywords[0],
                "heat_score": 70,
            } for index in range(count)]
            return keywords, candidates, []

        with patch.object(app, "search_media_crawler_candidates", side_effect=fake_crawler):
            app.collect_trend_materials(topics, ["bili", "dy"], material_limit=3)

        self.assertEqual(calls, ["bili", "dy"])
        self.assertEqual(len(topics[0]["materials"]), 3)
        self.assertEqual({item["platform"] for item in topics[0]["materials"]}, {"bili", "dy"})

    def test_36kr_hotlist_is_used_as_the_only_hotspot_source(self):
        first_day = [{"rank": 1, "title": "雷军谈智能汽车", "content": "小米创始人公开分享业务判断", "url": "https://36kr.com/p/100", "publishTime": "2026-08-23 09:00:00", "author": "36Kr"}]
        second_day = [{"rank": 2, "title": "张一鸣谈 AI", "content": "字节跳动相关商业热点", "url": "https://36kr.com/p/101", "publishTime": "2026-08-24 09:00:00", "author": "36Kr"}]

        with patch.object(app, "fetch_36kr_hotlist", side_effect=[second_day, first_day]):
            sources, warnings = app.fetch_hot_topic_sources(["中国企业家"], "2026-08-23", "2026-08-24")

        self.assertEqual(warnings, [])
        self.assertEqual(len(sources), 2)
        self.assertTrue(all(source["source_name"] == "36Kr" for source in sources))
        self.assertTrue(all(app.is_36kr_url(source["url"]) for source in sources))
        self.assertTrue(all(source["search_query"] == "36Kr 24 小时热榜" for source in sources))

    def test_people_pool_uses_http_hotlist_without_llm(self):
        hotlist = [
            {"rank": 1, "title": "雷军谈智能汽车", "content": "小米创始人雷军公开分享业务判断", "url": "https://36kr.com/p/100", "publishTime": "2026-08-24 09:00:00", "author": "36Kr"},
            {"rank": 2, "title": "张一鸣回应 AI 战略", "content": "字节跳动创始人张一鸣谈 AI 发展", "url": "https://36kr.com/p/101", "publishTime": "2026-08-24 10:00:00", "author": "36Kr"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(app, "fetch_36kr_hotlist", return_value=hotlist),
                patch.object(app, "llm_json", side_effect=AssertionError("people stage must not call LLM")),
                patch.object(app, "trend_person_pool_path", side_effect=lambda pool_id: root / f"{pool_id}.json"),
            ):
                pool = app.build_trend_person_pool("2026-08-24", "2026-08-24")

        self.assertEqual(pool["provider"], "36Kr 热点（HTTP）")
        self.assertEqual({item["name"] for item in pool["people"]}, {"雷军", "张一鸣"})
        self.assertTrue(all(item["sources"] for item in pool["people"]))

    def test_selected_people_rejects_more_than_six(self):
        with tempfile.TemporaryDirectory() as directory:
            pool_path = Path(directory) / "people.json"
            people = [{"person_id": f"person-{index:03d}", "name": f"人物{index}", "sources": []} for index in range(1, 8)]
            pool_path.write_text(json.dumps({"pool_id": "people-test", "people": people}, ensure_ascii=False), encoding="utf-8")
            with patch.object(app, "trend_person_pool_path", return_value=pool_path):
                with self.assertRaisesRegex(RuntimeError, "最多只能选择 6"):
                    app.load_selected_trend_people("people-test", [item["person_id"] for item in people])

    def test_hotspot_pool_splits_one_36kr_report_into_multiple_topics(self):
        sources = [{
            "title": "小米发布新车，京东调整即时零售策略",
            "description": "小米公布新车进展，京东同步宣布即时零售业务调整。",
            "url": "https://36kr.com/p/1000",
            "published_at": "2026-08-24",
            "heat_score": 95,
            "source_name": "36Kr",
        }]
        llm_result = {"hotspots": [
            {
                "source_id": "source_001",
                "title": "小米公布新车进展",
                "category": "产品发布",
                "summary": "小米公布新车进展。",
                "why_hot": "汽车新品动态受到关注。",
                "evidence_excerpt": "小米公布新车进展",
                "entities": ["小米", "新车"],
            },
            {
                "source_id": "source_001",
                "title": "京东调整即时零售策略",
                "category": "公司动态",
                "summary": "京东宣布即时零售业务调整。",
                "why_hot": "零售业务策略变化明确。",
                "evidence_excerpt": "京东同步宣布即时零售业务调整",
                "entities": ["京东", "即时零售"],
            },
        ]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(app, "fetch_hot_topic_sources", return_value=(sources, [])),
                patch.object(app, "llm_json", return_value=llm_result) as llm_request,
                patch.object(app, "trend_hotspot_pool_path", side_effect=lambda pool_id: root / f"{pool_id}.json"),
            ):
                pool = app.build_trend_hotspot_pool("2026-08-24", "2026-08-24")

        self.assertEqual(pool["provider"], "热点发现")
        self.assertEqual([item["title"] for item in pool["hotspots"]], ["小米公布新车进展", "京东调整即时零售策略"])
        self.assertTrue(all(item["source_url"] == "https://36kr.com/p/1000" for item in pool["hotspots"]))
        self.assertIn("一篇报道可能把多个独立新闻", llm_request.call_args.args[0])

    def test_selected_hotspots_generate_queries_and_keep_missing_material(self):
        hotspots = [
            {
                "hotspot_id": "hotspot-001", "title": "小米公布新车进展", "category": "产品发布",
                "summary": "小米公布新车进展。", "why_hot": "新品动态。", "evidence_excerpt": "小米公布新车进展",
                "entities": ["小米", "SU7"], "source_title": "混合报道", "source_url": "https://36kr.com/p/1000",
                "source_name": "36Kr", "published_at": "2026-08-24", "heat_score": 95,
            },
            {
                "hotspot_id": "hotspot-002", "title": "未选择的行业消息", "category": "行业趋势",
                "summary": "不应参与检索。", "why_hot": "测试。", "evidence_excerpt": "不应参与检索",
                "entities": ["不应检索"], "source_title": "混合报道", "source_url": "https://36kr.com/p/1000",
                "source_name": "36Kr", "published_at": "2026-08-24", "heat_score": 90,
            },
            {
                "hotspot_id": "hotspot-003", "title": "京东调整即时零售策略", "category": "公司动态",
                "summary": "京东调整即时零售业务。", "why_hot": "策略变化。", "evidence_excerpt": "京东调整即时零售业务",
                "entities": ["京东", "即时零售"], "source_title": "混合报道", "source_url": "https://36kr.com/p/1000",
                "source_name": "36Kr", "published_at": "2026-08-24", "heat_score": 88,
            },
        ]
        llm_result = {"topics": [{
            "hotspot_id": "hotspot-001", "title": "小米新车进展", "category": "产品发布",
            "subject_label": "小米、SU7", "statement_summary": "小米公布新车进展。",
            "heat_reason": "新品动态。", "evidence_excerpt": "小米公布新车进展", "source_confidence": "high",
            "verified_anchors": ["小米", "SU7"], "material_queries": ["小米 SU7 发布会"], "match_terms": ["小米", "SU7"], "recommendation_reason": "用户选中的产品热点。",
        }]}
        searched_queries = []

        def fake_crawler(keywords, platform, _limit, *_args):
            searched_queries.extend(keywords)
            if "小米" not in keywords[0]:
                return keywords, [], []
            return keywords, [{
                "candidate_id": "xiaomi-video", "title": "小米 SU7 发布会现场", "description": "新车发布会直播回放。",
                "url": f"https://video.test/{platform}/xiaomi", "platform": platform, "author": "媒体",
                "published_at": "2026-08-24", "keyword": keywords[0], "heat_score": 80,
            }], []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pool_path = root / "hotspots.json"
            result_path = root / "result.json"
            pool_path.write_text(json.dumps({"pool_id": "hotspots-test", "source_count": 1, "hotspots": hotspots, "warnings": []}, ensure_ascii=False), encoding="utf-8")
            with (
                patch.object(app, "trend_knowledge_context", return_value=[{"主题": "科技商业"}]),
                patch.object(app, "llm_json", return_value=llm_result),
                patch.object(app, "fetch_source_article_content", return_value={"content": "小米公布SU7新车进展，京东同步宣布即时零售业务调整。", "source": "test"}),
                patch.object(app, "search_media_crawler_candidates", side_effect=fake_crawler),
                patch.object(app, "trend_hotspot_pool_path", return_value=pool_path),
                patch.object(app, "trend_search_path", return_value=result_path),
            ):
                result = app.discover_ai_trends({
                    "hotspot_pool_id": "hotspots-test", "hotspot_ids": ["hotspot-001", "hotspot-003"], "platforms": ["bili"],
                })
                result_written = result_path.exists()

        self.assertEqual([item["hotspot_id"] for item in result["selected_hotspots"]], ["hotspot-001", "hotspot-003"])
        self.assertEqual(len(result["topics"]), 2)
        self.assertTrue(result["topics"][0]["materials"])
        self.assertFalse(result["topics"][1]["materials"])
        self.assertTrue(any("小米" in query for query in searched_queries))
        self.assertTrue(any("京东" in query for query in searched_queries))
        self.assertFalse(any("不应检索" in query for query in searched_queries))
        self.assertTrue(result_written)

    def test_hotspot_queries_add_verified_company_anchors_to_generic_llm_terms(self):
        hotspot = {
            "hotspot_id": "hotspot-mrna",
            "title": "Moderna与默沙东的个性化mRNA癌症疗法III期试验取得成功",
            "category": "医疗科技",
            "summary": "Moderna与默沙东宣布个性化mRNA癌症疗法在高危黑色素瘤全球III期试验取得成功。",
            "why_hot": "联合研发和关键临床进展。",
            "evidence_excerpt": "首款个性化mRNA癌症疗法intismeran autogene在高危黑色素瘤全球III期临床试验取得成功。",
            "entities": ["Moderna", "默沙东", "intismeran autogene", "高危黑色素瘤"],
            "source_title": "两家药企公布个性化mRNA癌症疗法III期临床进展",
            "source_url": "https://36kr.com/p/mrna",
            "source_name": "36Kr",
            "published_at": "2026-08-25",
            "source_article_text": "全球mRNA巨头Moderna与默沙东联合宣布，他们研发的首款个性化mRNA癌症疗法intismeran autogene，在针对高危黑色素瘤的全球III期临床试验中取得成功。",
        }
        llm_result = {
            "topics": [{
                "hotspot_id": "hotspot-mrna",
                "title": "个性化mRNA癌症疗法临床进展",
                "category": "医疗科技",
                "subject_label": "mRNA癌症疗法",
                "statement_summary": hotspot["summary"],
                "heat_reason": hotspot["why_hot"],
                "evidence_excerpt": hotspot["evidence_excerpt"],
                "source_confidence": "high",
                "verified_anchors": ["Moderna", "默沙东", "intismeran autogene", "不存在的主体"],
                "material_queries": ["AI 治疗癌症", "mRNA 癌症疗法"],
                "match_terms": ["AI", "癌症", "mRNA"],
                "recommendation_reason": "临床试验进展。",
            }]
        }
        with patch.object(app, "llm_json", return_value=llm_result) as llm_request:
            topics = app.generate_trend_topics_from_hotspots([hotspot], [])

        self.assertEqual(len(topics), 1)
        topic = topics[0]
        self.assertTrue(all("Moderna" in query and "默沙东" in query for query in topic["material_queries"]))
        self.assertEqual(topic["search_anchors"][:2], ["Moderna", "默沙东"])
        self.assertNotIn("不存在的主体", topic["search_anchors"])
        self.assertIn(hotspot["source_article_text"], llm_request.call_args.args[0])
        irrelevant = {"title": "AI治疗癌症的研究综述", "description": "泛泛讨论癌症治疗。", "author": "医学频道"}
        relevant = {"title": "Moderna与默沙东公布mRNA癌症疗法进展", "description": "黑色素瘤III期临床试验。", "author": "权威媒体"}
        self.assertFalse(app.material_candidate_quality(irrelevant, topic)[3])
        self.assertTrue(app.material_candidate_quality(relevant, topic)[3])

    def test_generic_human_ai_cancer_terms_cannot_trigger_media_search(self):
        hotspot = {
            "hotspot_id": "hotspot-generic",
            "title": "人类历史上第一次用AI治愈癌症",
            "category": "AI医疗",
            "summary": "人类历史上第一次用AI治愈癌症。",
            "evidence_excerpt": "人类历史上第一次用AI治愈癌症。",
            "entities": ["人类", "AI", "癌症", "史上首次"],
            "source_article_text": "人类历史上第一次用AI治愈癌症。",
        }
        llm_result = {"topics": [{
            "hotspot_id": "hotspot-generic",
            "title": hotspot["title"],
            "verified_anchors": ["人类", "AI", "癌症"],
            "material_queries": ["人类 首次 AI 治愈癌症 新闻现场"],
            "match_terms": ["人类", "AI", "癌症"],
        }]}

        with patch.object(app, "llm_json", return_value=llm_result):
            topic = app.generate_trend_topics_from_hotspots([hotspot], [])[0]

        self.assertEqual(topic["query_generation"], "anchor_missing")
        self.assertEqual(topic["search_anchors"], [])
        self.assertEqual(topic["material_queries"], [])

    def test_selected_hotspots_rejects_more_than_ten(self):
        with tempfile.TemporaryDirectory() as directory:
            pool_path = Path(directory) / "hotspots.json"
            hotspots = [{"hotspot_id": f"hotspot-{index:03d}", "title": f"热点{index}"} for index in range(1, 12)]
            pool_path.write_text(json.dumps({"pool_id": "hotspots-test", "hotspots": hotspots}, ensure_ascii=False), encoding="utf-8")
            with patch.object(app, "trend_hotspot_pool_path", return_value=pool_path):
                with self.assertRaisesRegex(RuntimeError, "最多只能选择 10"):
                    app.load_selected_trend_hotspots("hotspots-test", [item["hotspot_id"] for item in hotspots])

    def test_task_center_lists_and_deletes_saved_trend_search_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            search_id = "trend-20260825-120000-abcdef12"
            search_path = root / f"{search_id}.json"
            people_pool = root / "people-20260825-120000-abcdef12.json"
            search_path.write_text(json.dumps({
                "search_id": search_id,
                "created_at": "2026-08-25T12:00:00",
                "selected_hotspots": [{"hotspot_id": "hotspot-001", "title": "小米新车进展"}],
                "selected_people": [{"person_id": "person-001", "name": "雷军"}],
                "topics": [{"speaker_name": "雷军", "materials": [{"candidate_id": "video-1"}]}],
                "candidates": [{"candidate_id": "video-1"}],
            }, ensure_ascii=False), encoding="utf-8")
            people_pool.write_text("{}", encoding="utf-8")
            previous_tasks = app.TREND_TASKS
            app.TREND_TASKS = {}
            try:
                with patch.object(app, "TRENDS_DIR", root):
                    records = app.list_trend_search_task_records()
                    self.assertEqual(len(records), 1)
                    self.assertEqual(records[0]["search_id"], search_id)
                    self.assertEqual(records[0]["category"], "trend")
                    self.assertIn("小米新车进展", records[0]["title"])

                    deleted = app.delete_task_record(records[0]["task_id"])
            finally:
                app.TREND_TASKS = previous_tasks

            self.assertEqual(deleted["kind"], "trend_record")
            self.assertFalse(search_path.exists())
            self.assertTrue(people_pool.exists())

    def test_36kr_hotlist_uses_recent_local_cache_when_network_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "trend-cache.json").write_text(json.dumps({
                "topics": [{
                    "source_title": "董明珠谈制造业人才",
                    "source_url": "https://36kr.com/p/cache-1",
                    "evidence_excerpt": "董明珠公开分享制造业人才判断。",
                    "published_at": "2026-08-19",
                }]
            }, ensure_ascii=False), encoding="utf-8")
            with (
                patch.object(app, "TRENDS_DIR", root),
                patch.object(app, "fetch_36kr_hotlist", side_effect=RuntimeError("系统拒绝了外部网络连接（WinError 10013）")),
            ):
                sources, warnings = app.fetch_hot_topic_sources(["中国企业家"], "2026-08-18", "2026-08-24")

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["source_name"], "36Kr（本地缓存）")
        self.assertIn("本地缓存", warnings[0])

    def test_source_article_body_is_cached_for_verified_query_anchors(self):
        article_body = (
            "Moderna与默沙东联合宣布，个性化mRNA癌症疗法intismeran autogene在高危黑色素瘤全球III期临床试验中取得成功。"
            "这项研究面向术后复发风险较高的患者，双方表示将继续收集长期随访数据，并推进后续监管沟通和商业化准备。"
        )
        page = (
            '<html><head><script type="application/ld+json">'
            + json.dumps({"@type": "NewsArticle", "articleBody": article_body}, ensure_ascii=False)
            + "</script></head><body></body></html>"
        ).encode("utf-8")
        response = type("Response", (), {
            "read": lambda self: page,
            "__enter__": lambda self: self,
            "__exit__": lambda self, *_args: False,
        })()
        with tempfile.TemporaryDirectory() as directory:
            cache_dir = Path(directory) / "article-cache"
            with (
                patch.object(app, "TREND_ARTICLE_CACHE_DIR", cache_dir),
                patch.object(app, "open_public_request", return_value=response) as open_request,
            ):
                first = app.fetch_source_article_content("https://36kr.com/p/mrna")
                second = app.fetch_source_article_content("https://36kr.com/p/mrna")

        self.assertEqual(first["content"], article_body)
        self.assertEqual(first["source"], "network")
        self.assertEqual(second["content"], article_body)
        self.assertEqual(second["source"], "cache")
        open_request.assert_called_once()

    def test_source_article_reader_falls_back_to_regional_36kr_page(self):
        article_body = (
            "Moderna与默沙东联合宣布，个性化mRNA癌症疗法intismeran autogene在高危黑色素瘤全球III期临床试验中取得成功。"
            "双方将继续推进长期随访、监管沟通和后续商业化准备。"
        )
        page = (
            '<html><head><script type="application/ld+json">'
            + json.dumps({"@type": "NewsArticle", "articleBody": article_body}, ensure_ascii=False)
            + "</script></head><body></body></html>"
        ).encode("utf-8")
        response = type("Response", (), {
            "read": lambda self: page,
            "__enter__": lambda self: self,
            "__exit__": lambda self, *_args: False,
        })()
        calls = []

        def open_request(request, timeout):
            calls.append(request.full_url)
            if request.full_url.startswith("https://36kr.com/"):
                raise app.ExternalNetworkError("直连被拒绝")
            return response

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(app, "TREND_ARTICLE_CACHE_DIR", Path(directory)),
                patch.object(app, "open_public_request", side_effect=open_request),
            ):
                result = app.fetch_source_article_content("https://36kr.com/p/3947532745489543?channel=skills")

        self.assertEqual(result["content"], article_body)
        self.assertEqual(result["resolved_url"], "https://eu.36kr.com/zh/p/3947532745489543")
        self.assertEqual(calls[:2], [
            "https://36kr.com/p/3947532745489543?channel=skills",
            "https://eu.36kr.com/zh/p/3947532745489543",
        ])

    def test_bing_search_uses_proxy_aware_request_opener(self):
        response = type("Response", (), {
            "read": lambda self: b"<rss><channel></channel></rss>",
            "__enter__": lambda self: self,
            "__exit__": lambda self, *_args: False,
        })()
        with patch.object(app, "open_public_request", return_value=response) as open_request:
            matched, outside_range = app.fetch_bing_video_candidates("test", ["test"])

        self.assertEqual(matched, [])
        self.assertEqual(outside_range, [])
        open_request.assert_called_once()

    def test_external_network_error_is_not_mislabeled_as_llm(self):
        blocked_reason = type("BlockedReason", (), {"winerror": 10013})()
        blocked = app.urllib.error.URLError(blocked_reason)
        with patch.object(app, "http_openers", return_value=[type("Blocked", (), {"open": lambda *_args, **_kwargs: (_ for _ in ()).throw(blocked)})()]):
            with self.assertRaises(app.ExternalNetworkError) as raised:
                app.open_public_request("request", timeout=1)

        self.assertIn("外部网络连接", str(raised.exception))
        self.assertNotIn("LLM 服务", str(raised.exception))

    def test_proxy_failure_falls_back_to_direct_opener(self):
        proxy_error = app.urllib.error.URLError("proxy unavailable")
        response = object()
        proxy = type("Proxy", (), {"open": lambda *_args, **_kwargs: (_ for _ in ()).throw(proxy_error)})()
        direct = type("Direct", (), {"open": lambda *_args, **_kwargs: response})()
        with patch.object(app, "http_openers", return_value=(proxy, direct)):
            self.assertIs(app.open_public_request("request", timeout=1), response)

    def test_windows_proxy_is_only_read_when_proxy_enable_is_on(self):
        with patch.object(app, "_windows_system_proxy_url", return_value=""):
            self.assertEqual(app.public_proxy_url(), "")
            self.assertEqual(len(app.http_openers()), 1)
        with patch.object(app, "_windows_system_proxy_url", return_value="http://127.0.0.1:7897"):
            with patch.object(app, "proxy_http_opener", return_value=object()):
                self.assertEqual(app.public_proxy_url(), "http://127.0.0.1:7897")
                self.assertEqual(len(app.http_openers()), 2)

    def test_llm_model_catalog_uses_openai_models_endpoint(self):
        response = type("Response", (), {
            "read": lambda self: b'{"data":[{"id":"deepseek-v4-flash"},{"id":"deepseek-v4-pro"}]}',
            "__enter__": lambda self: self,
            "__exit__": lambda self, *_args: False,
        })()
        with patch.object(app, "open_public_request", return_value=response) as open_request:
            result = app.fetch_llm_models({
                "name": "deepseek",
                "api_key": "test-key",
                "base_url": "https://api.deepseek.com/chat/completions",
                "protocol": "openai",
            })

        self.assertEqual(result["models"], ["deepseek-v4-flash", "deepseek-v4-pro"])
        self.assertEqual(open_request.call_args.args[0].full_url, "https://api.deepseek.com/models")

    def test_llm_base_url_normalization_keeps_chat_endpoint_single(self):
        self.assertEqual(app.normalize_llm_base_url("https://api.example.com/v1/chat/completions"), "https://api.example.com/v1")
        self.assertEqual(app.llm_endpoint("https://api.example.com/v1/", "chat/completions"), "https://api.example.com/v1/chat/completions")

    def test_llm_json_parser_accepts_markdown_and_text_blocks(self):
        self.assertEqual(app.parse_llm_json_payload("说明如下：\n```json\n{\"ok\": true}\n```"), {"ok": True})
        self.assertEqual(app.parse_llm_json_payload([{"type": "text", "text": "{\"ok\": true}"}]), {"ok": True})

    def test_clip_analysis_reuses_shared_llm_request_path(self):
        provider = {
            "id": "provider-test",
            "name": "deepseek",
            "api_key": "test-key",
            "base_url": "https://api.deepseek.com",
            "protocol": "openai",
            "model": "deepseek-v4-pro",
            "enabled": True,
        }
        llm_result = {
            "clips": [{
                "title": "人物给出明确判断",
                "quote": "这是一个完整且清晰的判断。",
                "start": 1,
                "end": 20,
                "quote_score": 88,
                "context_score": 86,
                "edit_score": 82,
                "viral_score": 80,
                "confidence": 0.9,
            }]
        }
        with tempfile.TemporaryDirectory() as directory:
            base_dir = Path(directory)
            (base_dir / "transcript_grouped.json").write_text(json.dumps({
                "groups": [{"id": 1, "start": 0, "end": 22, "text": "这是一个完整且清晰的判断。"}]
            }, ensure_ascii=False), encoding="utf-8")
            (base_dir / "transcript.json").write_text(json.dumps({"segments": []}), encoding="utf-8")
            (base_dir / "metadata.json").write_text(json.dumps({"title": "测试视频", "duration": 30}, ensure_ascii=False), encoding="utf-8")
            with (
                patch.object(app, "job_dir", return_value=base_dir),
                patch.object(app, "enabled_provider", return_value=provider),
                patch.object(app, "llm_json", return_value=llm_result) as llm_request,
                patch.object(app, "http_opener", side_effect=AssertionError("clip analysis must use llm_json")),
                patch.object(app, "save_highlights"),
            ):
                result = app.deepseek_analyze(
                    "job-test",
                    {"target_clip_count": 1, "min_seconds": 8, "max_seconds": 45},
                )

        self.assertEqual(len(result["clips"]), 1)
        self.assertEqual(llm_request.call_args.kwargs["provider_id"], "provider-test")
        self.assertEqual(llm_request.call_args.kwargs["timeout"], 330)
        self.assertEqual(llm_request.call_args.kwargs["max_tokens"], 8192)

    def test_trend_query_planning_does_not_call_llm(self):
        with patch.object(app, "llm_json", side_effect=AssertionError("query planning should be local")):
            queries, focus = app.plan_trend_discovery_queries([{"主题": "任意偏好"}])

        self.assertEqual(len(queries), 4)
        self.assertTrue(focus)


if __name__ == "__main__":
    unittest.main()
