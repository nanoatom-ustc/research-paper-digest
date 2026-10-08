import html
import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import Config

logger = logging.getLogger(__name__)


class EmailSender:
    def __init__(self):
        self.sender = Config.EMAIL_SENDER
        self.password = Config.EMAIL_PASSWORD
        self.recipient = Config.RECIPIENT_EMAIL

    def send_digest(self, papers: list, summaries: list, failed_sources=None):
        current_date = datetime.now().strftime("%Y-%m-%d")
        try:
            msg = MIMEMultipart("alternative")
            status = "【数据不完整】" if failed_sources else ""
            msg["Subject"] = f"{status}论文摘要 - {current_date}"
            msg["From"] = self.sender
            msg["To"] = self.recipient

            if papers or failed_sources:
                text_content = self._build_text_content(papers, summaries, failed_sources)
                html_content = self._build_html_content(papers, summaries, failed_sources)
            else:
                text_content = self._build_no_papers_text()
                html_content = self._build_no_papers_html()

            msg.attach(MIMEText(text_content, "plain", "utf-8"))
            msg.attach(MIMEText(html_content, "html", "utf-8"))
            self._send_email(msg)
            logger.info("发送 %s 篇论文摘要 → %s", len(papers), self.recipient)
            return True
        except Exception as exc:
            logger.error("邮件发送失败: %s", exc)
            return False

    @staticmethod
    def _source_names():
        labels = {"arxiv": "arXiv", "aps": "APS"}
        return ", ".join(labels.get(source, source) for source in Config.SEARCH_SOURCES)

    def _build_no_papers_html(self):
        return f"""
        <!DOCTYPE html><html><head><meta charset="utf-8"></head>
        <body style="font-family:Arial,sans-serif;line-height:1.6">
          <h1>📭 今日无新论文</h1>
          <p>日期：{datetime.now().strftime('%Y年%m月%d日')}</p>
          <p><strong>数据源：</strong>{html.escape(self._source_names())}</p>
          <p><strong>关键词：</strong>{html.escape(', '.join(Config.SEARCH_KEYWORDS))}</p>
          <p>系统运行正常，但在配置的时间范围内未发现符合条件的新论文。</p>
        </body></html>
        """

    def _build_no_papers_text(self):
        return "\n".join([
            "论文监控报告",
            f"报告日期：{datetime.now().strftime('%Y-%m-%d')}",
            "状态：今日无新论文",
            f"数据源：{self._source_names()}",
            f"关键词：{', '.join(Config.SEARCH_KEYWORDS)}",
        ])

    @staticmethod
    def _failure_notice(failed_sources, has_papers):
        if not failed_sources:
            return ""
        status = "本次摘要不完整" if has_papers else "本次论文查询结果不可用或不完整"
        return (f"警告：{status}。数据源查询失败：{', '.join(failed_sources)}。"
                "仅包含成功获取的结果，无法确认是否有其他新论文。")

    def _build_text_content(self, papers, summaries, failed_sources=None):
        content = [
            "论文每日摘要",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"数据源: {self._source_names()}",
            f"共发现 {len(papers)} 篇相关论文",
            "=" * 60,
            "",
        ]
        notice = self._failure_notice(failed_sources, bool(papers))
        if notice:
            content.insert(0, notice)
        for index, (paper, summary) in enumerate(zip(papers, summaries), 1):
            content.extend([f"论文 #{index}: {paper['title']}", summary])
        return "\n".join(content)

    def _build_html_content(self, papers, summaries, failed_sources=None):
        del summaries  # summaries are used by the plain-text alternative
        notice = self._failure_notice(failed_sources, bool(papers))
        warning = f'<p role="alert" style="color:#a40000">{html.escape(notice)}</p>' if notice else ""
        cards = []
        for index, paper in enumerate(papers, 1):
            authors = ", ".join(paper.get("authors", [])[:3])
            if len(paper.get("authors", [])) > 3:
                authors += " 等"
            venue = paper.get("journal") or paper.get("primary_category") or "未知"
            link = paper.get("article_url") or paper.get("arxiv_url") or paper.get("pdf_url", "")
            abstract = paper.get("abstract", "")
            if len(abstract) > 500:
                abstract = abstract[:500] + "..."
            cards.append(f"""
            <div style="margin:20px 0;padding:16px;border:1px solid #ddd;border-radius:6px">
              <h2 style="font-size:18px">📄 #{index} {html.escape(paper.get('title', ''))}</h2>
              <p>🗂️ {html.escape(paper.get('source', ''))} · {html.escape(venue)}<br>
                 👥 {html.escape(authors)}<br>
                 📅 {html.escape(paper.get('published', ''))}<br>
                 🏷️ {html.escape(', '.join(paper.get('matched_keywords', [])))}</p>
              <p style="background:#f7f7f7;padding:10px">{html.escape(abstract)}</p>
              <a href="{html.escape(link, quote=True)}">🔗 查看文章</a>
            </div>
            """)

        return f"""
        <!DOCTYPE html><html><head><meta charset="utf-8"></head>
        <body style="font-family:Arial,sans-serif;line-height:1.6">
          <div style="background:#2c3e50;color:white;padding:20px;border-radius:6px">
            <h1>📚 论文每日摘要</h1>
            <p>{datetime.now().strftime('%Y年%m月%d日')} · {len(papers)} 篇 · {html.escape(self._source_names())}</p>
          </div>
          {warning}
          {''.join(cards)}
        </body></html>
        """

    def _send_email(self, msg):
        if "qq.com" in self.sender:
            server_factory, host, port = smtplib.SMTP, "smtp.qq.com", 587
        elif "163.com" in self.sender:
            server_factory, host, port = smtplib.SMTP, "smtp.163.com", 587
        else:
            server_factory, host, port = smtplib.SMTP_SSL, "smtp.qq.com", 465

        try:
            with server_factory(host, port, timeout=30) as server:
                if server_factory is smtplib.SMTP:
                    server.starttls()
                server.login(self.sender, self.password)
                server.send_message(msg)
        except Exception as exc:
            # Some QQ SMTP sessions report an SSL close error after accepting mail.
            if "(-1, b'\\x00\\x00\\x00')" in str(exc):
                logger.info("邮件已被服务器接受；忽略连接关闭错误")
                return
            raise

