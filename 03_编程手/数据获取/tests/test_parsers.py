from __future__ import annotations

import io
import json
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

from mtmcm_data import audit
from mtmcm_data.config import Source, load_config
from mtmcm_data.ziputil import expand_zip_names
from mtmcm_data.http import build_url
from mtmcm_data.manifest import Manifest, ManifestEntry, new_run_id
from mtmcm_data.parsers import article, copernicus, nasa_power, open_meteo, tpdc


def make_source(**overrides):
    base = dict(
        id="test",
        name="测试来源",
        kind="article",
        url="https://example.com/a",
        parser="article",
    )
    base.update(overrides)
    return Source(**base)


class TpdcParserTests(unittest.TestCase):
    def test_normalize_builds_citation_and_bbox(self):
        detail = {
            "code": "200",
            "context": {
                "metadataVO": {
                    "title": "示例数据集",
                    "titleEn": "Example Dataset",
                    "doi": "10.11888/Atmos.tpdc.999999",
                    "cstr": "18406.11.Atmos.tpdc.999999",
                    "west": 85.29,
                    "east": 85.29,
                    "south": 28.86,
                    "north": 28.86,
                    "startTime": "2021-04-26 20:00:00",
                    "endTime": "2026-08-27 08:00:00",
                    "description": "描述",
                    "instructions": "缺测 9999.9",
                    "useTerms": "注明来源",
                    "temporalResolution": "Hourly",
                    "spatialResolution": "<= 1m",
                    "tsPublish": "2026-09-08 10:00:00",
                    "status": 6,
                },
                "authorVOList": [
                    {"name": "马耀明", "nameEn": "MA Yaoming", "unit": "中国科学院青藏高原研究所"},
                    {"name": "马伟强", "nameEn": "MA Weiqiang", "unit": "中国科学院青藏高原研究所"},
                ],
                "themeList": [{"name": "大气"}],
                "relatedDataList": [],
                "literatureVOList": [],
            },
        }
        google = {
            "code": "200",
            "context": {
                "name": "示例数据集",
                "keywords": ["Soil", "Precipitation"],
                "creator": [{"name": "MA Yaoming"}, {"name": "MA Weiqiang"}],
                "publisher": {"name": "TPDC"},
                "datePublished": "2026-09-08",
            },
        }
        source = make_source(id="tpdc_x", kind="tpdc_dataset", metadata_id="abc")
        meta = tpdc.normalize(detail, google, source)
        self.assertEqual(meta["title"], "示例数据集")
        self.assertEqual(meta["doi"], "10.11888/Atmos.tpdc.999999")
        self.assertIn("马耀明", meta["citation_cn"])
        self.assertIn("2026", meta["citation_cn"])
        self.assertTrue(meta["spatial_coverage"]["is_point"])
        self.assertEqual(meta["time_coverage"]["start"], "2021-04-26 20:00:00")
        self.assertIn("Soil", meta["keywords"])
        self.assertEqual(meta["download_status"], "metadata_only")


class ArticleParserTests(unittest.TestCase):
    def test_parse_mnr_like_html(self):
        html = """
        <html><head>
        <meta name="ArticleTitle" content="泥石流形成的基本条件">
        <meta name="PubDate" content="2025-01-14 21:06">
        </head><body>
        <div class="ky_article_center">
          <p>一般认为泥石流发生需要三个基本条件：能量条件、物质条件和触发条件。</p>
          <p>能量条件主要通过区域地形条件体现。</p>
        </div>
        <script>var x = 1;</script>
        </body></html>
        """
        source = make_source(
            selectors={
                "title": "//meta[@name='ArticleTitle']/@content",
                "published": "//meta[@name='PubDate']/@content",
                "content": "//div[contains(@class,'ky_article_center')]",
            }
        )
        meta = article.parse(html, source)
        self.assertEqual(meta["title"], "泥石流形成的基本条件")
        self.assertEqual(meta["published_at"], "2025-01-14 21:06")
        self.assertEqual(meta["paragraph_count"], 2)
        self.assertIn("三个基本条件", meta["text"])
        self.assertNotIn("var x", meta["text"])

    def test_clean_text_removes_private_use(self):
        self.assertEqual(article.clean_text("a\ue004b\xa0c"), "ab c")


class ZipUtilTests(unittest.TestCase):
    def test_expand_nested_zip(self):
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as zf:
            zf.writestr("a.csv", "x")
            zf.writestr("b.csv", "y")
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w") as zf:
            zf.writestr("inner.zip", inner.getvalue())
            zf.writestr("readme.txt", "z")
        names, nested = expand_zip_names(outer.getvalue())
        self.assertEqual(names, {"a.csv", "b.csv", "readme.txt"})
        self.assertEqual(nested, ["inner.zip"])


class AuditTests(unittest.TestCase):
    def test_parse_station_time_without_leading_zero(self):
        parsed = audit.parse_station_time("2026-8-26 10:00")
        self.assertEqual(parsed, datetime(2026, 8, 26, 10, 0))

    def test_window_stats_skips_missing_sentinel(self):
        rows = [
            {"time": datetime(2026, 8, 26, 8), "row": {"Precip(mm)": "0.0"}},
            {"time": datetime(2026, 8, 26, 9), "row": {"Precip(mm)": "1.5"}},
            {"time": datetime(2026, 8, 26, 10), "row": {"Precip(mm)": "9999.9"}},
            {"time": datetime(2026, 8, 26, 11), "row": {"Precip(mm)": "0.5"}},
        ]
        stats = audit.window_stats(
            rows,
            column="Precip(mm)",
            start=datetime(2026, 8, 26, 8),
            end=datetime(2026, 8, 26, 10),
        )
        self.assertEqual(stats["slots"], 3)
        self.assertEqual(stats["valid"], 2)
        self.assertEqual(stats["missing"], 1)
        self.assertEqual(stats["sum"], 1.5)
        self.assertEqual(stats["nonzero_hours"], 1)


class ApiParserTests(unittest.TestCase):
    def test_open_meteo_rows(self):
        payload = {
            "latitude": 28.86,
            "longitude": 85.29,
            "elevation": 4138,
            "timezone": "Asia/Shanghai",
            "hourly_units": {"time": "iso8601", "temperature_2m": "°C"},
            "hourly": {
                "time": ["2026-08-26T09:00", "2026-08-26T10:00"],
                "temperature_2m": [8.1, 9.2],
            },
        }
        meta, rows = open_meteo.parse(payload, make_source(id="om", kind="api_json", parser="open_meteo"))
        self.assertEqual(meta["row_count"], 2)
        self.assertEqual(rows[1]["temperature_2m"], 9.2)
        self.assertEqual(meta["units"]["temperature_2m"], "°C")

    def test_nasa_power_fill_value_to_none(self):
        payload = {
            "header": {"fill_value": -999.0, "time_standard": "LST"},
            "parameters": {"T2M": {"units": "C", "longname": "2m temperature"}},
            "properties": {"parameter": {"T2M": {"2026082609": 8.1, "2026082610": -999.0}}},
            "geometry": {"coordinates": [85.29, 28.86, 4995.62]},
        }
        meta, rows = nasa_power.parse(payload, make_source(id="np", kind="api_json", parser="nasa_power"))
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[1]["T2M"])
        self.assertEqual(meta["elevation_m"], 4995.62)

    def test_copernicus_bbox(self):
        payload = {
            "value": [
                {
                    "Id": "p1",
                    "Name": "S2B_MSIL2A_TEST",
                    "ContentDate": {"Start": "2026-08-26T00:00:00Z", "End": "2026-08-26T00:10:00Z"},
                    "ContentLength": 1000000,
                    "Online": True,
                    "S3Path": "/eodata/x",
                    "GeoFootprint": {
                        "type": "Polygon",
                        "coordinates": [[[85.0, 28.5], [85.5, 28.5], [85.5, 29.0], [85.0, 29.0], [85.0, 28.5]]],
                    },
                }
            ]
        }
        source = make_source(
            id="s2",
            kind="api_json",
            parser="copernicus",
            study_area={"west": 85.1, "south": 28.4, "east": 85.4, "north": 28.8},
        )
        meta, rows = copernicus.parse(payload, source)
        self.assertEqual(meta["row_count"], 1)
        self.assertAlmostEqual(rows[0]["bbox_west"], 85.0)
        self.assertAlmostEqual(rows[0]["bbox_north"], 29.0)
        self.assertEqual(rows[0]["product_type"], "MSIL2A")
        self.assertTrue(rows[0]["core_overlap"])
        self.assertEqual(meta["core_overlap_count"], 1)


class ConfigAndManifestTests(unittest.TestCase):
    def test_config_has_all_sources(self):
        config = load_config()
        self.assertGreaterEqual(len(config.sources), 15)
        self.assertEqual(config.get("tpdc_01_hourly").metadata_id, "5b09afd1-d11b-4150-a291-50f0484dddf1")
        self.assertEqual(config.get("copernicus_s2").study_area["west"], 85.15)
        self.assertEqual(config.get("baike_debris_flow").manual_snapshot, "data/manual/baike_debris_flow.html")
        self.assertTrue(config.get("baike_debris_flow").enabled)
        self.assertTrue(config.get("baike_debris_flow").allow_blocked)

    def test_manifest_roundtrip(self):
        path = Path("data") / "test_manifest.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        try:
            manifest = Manifest(path)
            entry = ManifestEntry(
                run_id=new_run_id(),
                source_id="s",
                source_name="S",
                kind="article",
                url="https://example.com",
                status=200,
                fetched_at="2026-10-24T00:00:00+00:00",
                sha256="abc",
                bytes=3,
            )
            manifest.append(entry)
            self.assertEqual(len(manifest.read_all()), 1)
            self.assertEqual(manifest.latest_by_source()["s"]["status"], 200)
        finally:
            path.unlink(missing_ok=True)

    def test_build_url_preserves_chinese_and_query(self):
        url = build_url("https://example.com/a?x=1", {"q": "泥石流", "$filter": "A eq 'B'"})
        self.assertIn("x=1", url)
        self.assertIn("%E6%B3%A5%E7%9F%B3%E6%B5%81", url)
        self.assertIn("%24filter=", url)


if __name__ == "__main__":
    unittest.main()
