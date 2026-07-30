"""报告生成器。

把多个图表 + LLM 文字分析拼接成一个完整的 HTML 报告。

使用方式：
    generator = ReportGenerator(llm_client)
    report_html = await generator.generate(
        title="中国 GDP 分析报告",
        datasets=[viz_dataset1, viz_dataset2],
        charts=[chart_html1, chart_html2],
        user_prompt="分析中国 GDP 趋势",
    )
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from service.viz_data.schema import VizDataset


class ReportGenerator:
    """HTML 报告生成器。"""
    
    # 报告 HTML 模板
    REPORT_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 40px 20px;
        }}
        .header {{
            text-align: center;
            margin-bottom: 50px;
            padding-bottom: 30px;
            border-bottom: 2px solid #e0e0e0;
        }}
        .header h1 {{
            font-size: 32px;
            font-weight: 700;
            color: #1a1a1a;
            margin-bottom: 15px;
        }}
        .header .meta {{
            color: #666;
            font-size: 14px;
        }}
        .disclaimer {{
            background: #fff3cd;
            border: 1px solid #ffeaa7;
            border-radius: 8px;
            padding: 15px 20px;
            margin-bottom: 40px;
            font-size: 13px;
            color: #856404;
        }}
        .disclaimer strong {{
            display: block;
            margin-bottom: 5px;
        }}
        .section {{
            background: #fff;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }}
        .section h2 {{
            font-size: 22px;
            font-weight: 600;
            color: #1a1a1a;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid #eee;
        }}
        .section .content {{
            font-size: 15px;
            line-height: 1.8;
            color: #444;
        }}
        .section .content p {{
            margin-bottom: 15px;
        }}
        .section .chart-container {{
            margin-top: 25px;
            border: 1px solid #eee;
            border-radius: 8px;
            overflow: hidden;
        }}
        .source-note {{
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px dashed #ddd;
            font-size: 12px;
            color: #999;
        }}
        .footer {{
            text-align: center;
            padding: 30px;
            color: #999;
            font-size: 12px;
        }}
        .toc {{
            background: #f8f9fa;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 30px;
        }}
        .toc h3 {{
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 15px;
            color: #333;
        }}
        .toc ul {{
            list-style: none;
        }}
        .toc li {{
            padding: 8px 0;
            border-bottom: 1px solid #eee;
            font-size: 14px;
        }}
        .toc li:last-child {{
            border-bottom: none;
        }}
        .toc a {{
            color: #0066cc;
            text-decoration: none;
        }}
        .toc a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{title}</h1>
            <div class="meta">
                生成时间：{generated_at} | 数据来源：{data_sources}
            </div>
        </div>
        
        <div class="disclaimer">
            <strong>⚠️ 免责声明</strong>
            本报告由 AI 自动生成，数据来源于公开渠道，仅供参考学习使用。
            报告中的分析、预测和结论不构成任何投资建议或决策依据。
            据此操作产生的任何风险由使用者自行承担。
        </div>
        
        <div class="toc">
            <h3>📑 目录</h3>
            <ul>
                {toc_items}
            </ul>
        </div>
        
        {sections}
        
        <div class="footer">
            <p>本报告由 AI 数据可视化系统自动生成</p>
            <p>生成时间：{generated_at}</p>
        </div>
    </div>
</body>
</html>
    """
    
    SECTION_TEMPLATE = """
        <div class="section" id="section-{index}">
            <h2>{title}</h2>
            <div class="content">
                {content}
            </div>
            {chart_html}
            {source_note}
        </div>
    """
    
    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: LLM 客户端（用于生成文字分析）
        """
        self.llm_client = llm_client
    
    async def generate(
        self,
        title: str,
        datasets: List[VizDataset],
        charts: List[str],
        user_prompt: str = "",
    ) -> str:
        """生成完整的 HTML 报告。
        
        Args:
            title: 报告标题
            datasets: 数据集列表（用于数据来源标注和摘要）
            charts: 图表 HTML 列表
            user_prompt: 用户的原始需求（用于 LLM 生成分析文字）
            
        Returns:
            完整的 HTML 报告字符串
        """
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 收集数据来源
        data_sources = self._collect_data_sources(datasets)
        
        # 生成章节内容
        sections = await self._generate_sections(datasets, charts, user_prompt)
        
        # 生成目录
        toc_items = self._generate_toc(sections)

        # 把 section dict 列表渲染成 HTML 字符串
        section_htmls = []
        for idx, sec in enumerate(sections):
            section_htmls.append(
                f'<section id="section-{idx + 1}">\n'
                f'<h2>{sec.get("title", "")}</h2>\n'
                f'<div class="content">{sec.get("content", "")}</div>\n'
                f'{sec.get("chart_html", "")}\n'
                f'{sec.get("source_note", "")}\n'
                f'</section>'
            )

        # 渲染最终报告
        return self.REPORT_TEMPLATE.format(
            title=title,
            generated_at=generated_at,
            data_sources=data_sources,
            toc_items=toc_items,
            sections="\n".join(section_htmls),
        )
    
    def _collect_data_sources(self, datasets: List[VizDataset]) -> str:
        """收集所有数据集的来源信息。"""
        sources = set()
        for ds in datasets:
            if ds.descriptor and ds.descriptor.extra:
                src = ds.descriptor.extra.get("source")
                if src:
                    sources.add(src)
            elif ds.name:
                sources.add(ds.name)
        
        if not sources:
            return "用户上传"
        
        return "、".join(sorted(sources))
    
    def _generate_toc(self, sections: List[Dict[str, str]]) -> str:
        """生成目录 HTML。"""
        toc_html = ""
        for idx, section in enumerate(sections):
            title = section.get("title", f"第 {idx + 1} 章")
            toc_html += f'<li><a href="#section-{idx + 1}">{idx + 1}. {title}</a></li>\n'
        return toc_html
    
    async def _generate_sections(
        self,
        datasets: List[VizDataset],
        charts: List[str],
        user_prompt: str,
    ) -> List[Dict[str, str]]:
        """生成报告章节内容。
        
        每个章节包含：标题 + 文字分析 + 图表 + 数据来源标注。
        """
        sections = []
        
        # 1. 第一章：数据摘要
        summary_section = await self._generate_summary_section(datasets, user_prompt)
        sections.append(summary_section)
        
        # 2. 每个图表一个章节（分析 + 图表）
        for chart_idx, chart_html in enumerate(charts):
            section = await self._generate_chart_section(
                chart_idx,
                chart_html,
                datasets,
                user_prompt,
            )
            sections.append(section)
        
        # 3. 最后一章：结论建议
        conclusion_section = await self._generate_conclusion_section(datasets, user_prompt)
        sections.append(conclusion_section)
        
        return sections
    
    async def _generate_summary_section(
        self,
        datasets: List[VizDataset],
        user_prompt: str,
    ) -> Dict[str, str]:
        """生成摘要章节。"""
        # 构建数据摘要
        data_summary = self._build_data_summary(datasets)
        
        # LLM 生成摘要文字
        if self.llm_client:
            prompt = f"""
请基于以下数据摘要，写一份简洁的报告摘要（300 字以内）：

数据摘要：
{data_summary}

用户需求：{user_prompt or "分析数据趋势"}

要求：
1. 概括主要数据特征和趋势
2. 语言专业、客观
3. 不要使用"我"、"我们"等人称代词
4. 不要做过度解读，只陈述事实
"""
            try:
                content = await self._call_llm(prompt)
            except Exception:
                content = self._fallback_summary(datasets)
        else:
            content = self._fallback_summary(datasets)
        
        return {
            "title": "📊 数据摘要",
            "content": content,
            "chart_html": "",
            "source_note": "",
        }
    
    async def _generate_chart_section(
        self,
        chart_idx: int,
        chart_html: str,
        datasets: List[VizDataset],
        user_prompt: str,
    ) -> Dict[str, str]:
        """生成图表分析章节。"""
        section_title = f"📈 图表 {chart_idx + 1}：趋势分析"
        
        # 生成分析文字
        if self.llm_client:
            data_summary = self._build_data_summary(datasets)
            prompt = f"""
基于以下数据，为第 {chart_idx + 1} 张图表写一段分析文字（200 字以内）：

数据摘要：
{data_summary}

用户需求：{user_prompt or "分析数据趋势"}

要求：
1. 聚焦图表展示的数据趋势
2. 指出关键转折点或极值
3. 语言客观、数据驱动
4. 不要过度解读
"""
            try:
                content = await self._call_llm(prompt)
            except Exception:
                content = "数据趋势分析：详见上方图表。"
        else:
            content = "数据趋势分析：详见上方图表。"
        
        # 数据来源标注
        source_note = self._build_source_note(datasets)
        
        return {
            "title": section_title,
            "content": content,
            "chart_html": f'<div class="chart-container">{chart_html}</div>',
            "source_note": source_note,
        }
    
    async def _generate_conclusion_section(
        self,
        datasets: List[VizDataset],
        user_prompt: str,
    ) -> Dict[str, str]:
        """生成结论建议章节。"""
        if self.llm_client:
            data_summary = self._build_data_summary(datasets)
            prompt = f"""
基于以下数据，写一份简洁的结论和建议（300 字以内）：

数据摘要：
{data_summary}

用户需求：{user_prompt or "分析数据趋势"}

要求：
1. 基于数据给出客观结论
2. 建议要务实、可操作
3. 强调"基于现有数据"，不要过度外推
4. 语言专业、克制
"""
            try:
                content = await self._call_llm(prompt)
            except Exception:
                content = "结论：本报告基于公开数据分析生成，仅供参考。"
        else:
            content = "结论：本报告基于公开数据分析生成，仅供参考。"
        
        return {
            "title": "💡 结论与建议",
            "content": content,
            "chart_html": "",
            "source_note": "",
        }
    
    def _build_data_summary(self, datasets: List[VizDataset]) -> str:
        """构建数据摘要字符串（供 LLM 使用）。"""
        lines = []
        for idx, ds in enumerate(datasets):
            if ds.tabular and ds.tabular.preview_rows:
                cols = ds.tabular.preview_rows[0]
                rows_count = ds.tabular.row_count
                lines.append(f"数据集 {idx + 1}：{ds.name}")
                lines.append(f"  - 行数：{rows_count}")
                lines.append(f"  - 列名：{', '.join(map(str, cols))}")
                if len(ds.tabular.preview_rows) > 1:
                    sample_row = ds.tabular.preview_rows[1]
                    lines.append(f"  - 示例行：{sample_row}")
        return "\n".join(lines)
    
    def _build_source_note(self, datasets: List[VizDataset]) -> str:
        """构建数据来源标注 HTML。"""
        sources = set()
        for ds in datasets:
            if ds.descriptor and ds.descriptor.extra:
                src = ds.descriptor.extra.get("source")
                if src:
                    sources.add(src)
        
        if not sources:
            return ""
        
        return f"""
        <div class="source-note">
            📌 数据来源：{"、".join(sorted(sources))}
        </div>
        """
    
    def _fallback_summary(self, datasets: List[VizDataset]) -> str:
        """LLM 不可用时的降级摘要。"""
        total_rows = sum(ds.tabular.row_count for ds in datasets if ds.tabular)
        return f"""
<p>本报告基于 {len(datasets)} 个数据集、共 {total_rows} 行数据分析生成。</p>
<p>数据涵盖宏观经济指标、行业统计等多个维度，通过可视化图表展示趋势变化。</p>
<p>所有数据来源于公开渠道，报告内容仅供参考学习。</p>
"""
    
    async def _call_llm(self, prompt: str) -> str:
        """调用 LLM 生成文字。"""
        if not self.llm_client:
            return ""
        
        # 这里适配你的 LLM 客户端接口
        # 如果用的是 LangChain，直接返回 result.content
        result = await self.llm_client.ainvoke(prompt)
        if hasattr(result, "content"):
            return result.content
        return str(result)
    
    def render_sections_to_html(self, sections: List[Dict[str, str]]) -> str:
        """把章节数据渲染成 HTML 字符串。"""
        html_parts = []
        for idx, section in enumerate(sections):
            html = self.SECTION_TEMPLATE.format(
                index=idx + 1,
                title=section["title"],
                content=section["content"],
                chart_html=section.get("chart_html", ""),
                source_note=section.get("source_note", ""),
            )
            html_parts.append(html)
        return "\n".join(html_parts)


# 便捷函数：直接保存报告到文件
async def generate_and_save_report(
    output_path: str | Path,
    title: str,
    datasets: List[VizDataset],
    charts: List[str],
    user_prompt: str = "",
    llm_client=None,
) -> Path:
    """生成报告并保存到文件。
    
    Args:
        output_path: 输出文件路径
        title: 报告标题
        datasets: 数据集列表
        charts: 图表 HTML 列表
        user_prompt: 用户需求
        llm_client: LLM 客户端
        
    Returns:
        保存的文件路径
    """
    generator = ReportGenerator(llm_client)
    report_html = await generator.generate(title, datasets, charts, user_prompt)
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_html, encoding="utf-8")
    
    return output_path
