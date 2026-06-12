"""基础回归测试：CLI 启动、check 报告导出、export 空结果"""
import json
import os
import sys
import tempfile
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data_catalog.cli import main as cli_main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def workdir(tmp_path):
    """创建带示例数据文件的临时工作目录"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sales.csv").write_text("date,amount\n2024-01-01,100\n", encoding="utf-8")
    (data_dir / "users.json").write_text('{"users": []}', encoding="utf-8")
    sub = data_dir / "sub"
    sub.mkdir()
    (sub / "metrics.csv").write_text("kpi,value\nrev,500\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def meta_csv(tmp_path):
    """批量导入元信息的 CSV"""
    p = tmp_path / "meta.csv"
    p.write_text(
        "file_path,name,source,update_frequency,authorization_scope,contact_name,contact_email,description\n"
        "sales.csv,销售明细,ERP,每日,内部,张三,zhangsan@a.com,日销售流水\n"
        "users.json,用户画像,数据仓库,每月,授权可见,李四,lisi@a.com,用户画像指标\n"
        "sub\\metrics.csv,KPI指标,BI系统,每周,公开,王五,wangwu@a.com,业务KPI\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def catalog_file(runner, workdir, meta_csv):
    """生成并批量导入了元信息的目录清单 JSON 文件路径"""
    cat_path = workdir / "catalog.json"
    with runner.isolated_filesystem(temp_dir=workdir):
        result = runner.invoke(cli_main, ["scan", str(workdir / "data"), "-o", str(cat_path)])
        assert result.exit_code == 0, f"scan failed: {result.output}"
        result = runner.invoke(
            cli_main,
            ["describe", "-c", str(cat_path), "--from-file", str(meta_csv), "--match-by", "file_path"],
        )
        assert result.exit_code == 0, f"describe import failed: {result.output}"
    return cat_path


# ============================================================
# 1. CLI 启动 / 帮助命令
# ============================================================
class TestCliStartup:
    def test_help_exists(self, runner):
        result = runner.invoke(cli_main, ["--help"])
        assert result.exit_code == 0
        assert "scan" in result.output
        assert "check" in result.output
        assert "export" in result.output
        assert "describe" in result.output
        assert "publish" in result.output

    def test_each_command_has_help(self, runner):
        for cmd in ["scan", "describe", "tag", "check", "publish", "export", "list", "show"]:
            result = runner.invoke(cli_main, [cmd, "--help"])
            assert result.exit_code == 0, f"{cmd} --help failed"
            assert "Usage" in result.output

    def test_no_dict_undefined_error(self, runner, workdir):
        """回归：导入/运行时不应出现 NameError: name 'Dict' is not defined"""
        cat_path = workdir / "cat.json"
        data_dir = workdir / "data"

        result = runner.invoke(cli_main, ["scan", str(data_dir), "-o", str(cat_path)])
        assert result.exit_code == 0
        assert "Dict" not in result.output

        result = runner.invoke(cli_main, ["check", "-c", str(cat_path)])
        assert result.exit_code == 0
        assert "NameError" not in result.output
        assert "Dict" not in result.output

        result = runner.invoke(cli_main, ["export", "-c", str(cat_path), "-o", str(workdir / "x.json"), "-f", "json"])
        assert result.exit_code == 0
        assert "NameError" not in result.output


# ============================================================
# 2. check 报告导出
# ============================================================
class TestCheckReport:
    def test_check_report_json(self, runner, catalog_file, workdir):
        report_path = workdir / "audit.json"
        result = runner.invoke(cli_main, ["check", "-c", str(catalog_file), "--report", str(report_path)])
        assert result.exit_code == 0
        assert report_path.exists()

        data = json.loads(report_path.read_text(encoding="utf-8"))
        assert "total_resources" in data
        assert data["total_resources"] == 3
        assert "summary" in data
        assert "by_severity" in data["summary"]
        assert "results" in data
        assert len(data["results"]) == 3
        for r in data["results"]:
            assert "resource_id" in r
            assert "resource_name" in r
            assert "severity" in r

    def test_check_report_csv(self, runner, catalog_file, workdir):
        report_path = workdir / "audit.csv"
        result = runner.invoke(cli_main, ["check", "-c", str(catalog_file), "--report", str(report_path)])
        assert result.exit_code == 0
        assert report_path.exists()

        content = report_path.read_text(encoding="utf-8-sig")
        lines = content.strip().splitlines()
        assert lines[0].startswith("resource_id")
        assert len(lines) >= 4  # header + 3 ok entries

    def test_check_report_captures_missing_fields(self, runner, workdir):
        """无元信息的目录 → 报告中应能看到缺失字段分级"""
        cat_path = workdir / "bare.json"
        data_dir = workdir / "data"
        runner.invoke(cli_main, ["scan", str(data_dir), "-o", str(cat_path)])
        report_path = workdir / "bare_audit.json"
        result = runner.invoke(cli_main, ["check", "-c", str(cat_path), "--report", str(report_path)])
        assert result.exit_code == 0

        data = json.loads(report_path.read_text(encoding="utf-8"))
        errors = [r for r in data["results"] if r["severity"] == "error"]
        assert len(errors) == 3
        for r in errors:
            assert "name" in r["missing_fields"]
            assert any(i["level"] == "error" for i in r["issues"])


# ============================================================
# 3. export 空筛选结果
# ============================================================
class TestExportEmpty:
    def test_export_empty_by_tag(self, runner, catalog_file, workdir):
        out = workdir / "empty_tag.json"
        result = runner.invoke(
            cli_main,
            ["export", "-c", str(catalog_file), "-o", str(out), "-f", "json", "--tag", "no-such-tag"],
        )
        assert result.exit_code == 0
        assert "没有匹配到任何资源" in result.output or "0 个资源" in result.output
        assert "未匹配的资源不会被包含" in result.output

        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["total"] == 0
        assert data["resources"] == []

    def test_export_empty_by_published(self, runner, catalog_file, workdir):
        out = workdir / "empty_pub.csv"
        result = runner.invoke(
            cli_main,
            ["export", "-c", str(catalog_file), "-o", str(out), "-f", "csv", "--only-published"],
        )
        assert result.exit_code == 0

        lines = out.read_text(encoding="utf-8-sig").strip().splitlines()
        assert len(lines) == 1  # 仅 header，无数据行
        assert "resource_id" in lines[0]

    def test_export_non_empty_when_no_filter(self, runner, catalog_file, workdir):
        """未使用筛选条件时应正常导出全部资源"""
        out = workdir / "all.json"
        result = runner.invoke(cli_main, ["export", "-c", str(catalog_file), "-o", str(out), "-f", "json"])
        assert result.exit_code == 0

        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["total"] == 3
        assert len(data["resources"]) == 3


# ============================================================
# 4. describe --from-file 批量导入
# ============================================================
class TestDescribeImport:
    def test_import_by_file_path(self, runner, workdir, meta_csv):
        cat_path = workdir / "cat.json"
        data_dir = workdir / "data"
        runner.invoke(cli_main, ["scan", str(data_dir), "-o", str(cat_path)])

        result = runner.invoke(
            cli_main,
            ["describe", "-c", str(cat_path), "--from-file", str(meta_csv), "--match-by", "file_path"],
        )
        assert result.exit_code == 0
        assert "成功匹配并更新 3 个资源" in result.output

        data = json.loads(cat_path.read_text(encoding="utf-8"))
        names = {r["file_path"]: r["name"] for r in data["resources"]}
        assert names["sales.csv"] == "销售明细"
        assert names["users.json"] == "用户画像"
