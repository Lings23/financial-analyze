"""Bounded official CNINFO PDFs and recent AKShare news with archived source bytes."""
import hashlib
import html
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

from ..domains import BASES, DomainDataset as D, DomainRecord
from ..errors import ProviderAuthError, ProviderError, ProviderSchemaError, TransientProviderError, ValidationError
from ..models import aware, digest, utcnow
from .akshare import AkShareSubprocessTransport
from .base import ProviderCapability
from .tushare import NoRedirect

SHANGHAI = timezone(timedelta(hours=8))


def document_url(url, kind):
    if not isinstance(url, str):
        raise ProviderSchemaError("document URL missing")
    parsed = urllib.parse.urlsplit(url)
    host = "static.cninfo.com.cn" if kind == "pdf" else "finance.eastmoney.com"
    pattern = r"/finalpage/\d{4}-\d{2}-\d{2}/\d+\.[pP][dD][fF]" if kind == "pdf" else r"/a/\d+\.html"
    if (parsed.scheme != "https" or parsed.netloc != host or parsed.query or parsed.fragment
            or not re.fullmatch(pattern, parsed.path)):
        raise ProviderSchemaError("source document URL outside fixed HTTPS allowlist")
    return url


class DocumentHTTPTransport:
    """One attempt, fixed public origins, no cookies/credentials/redirects."""
    def __call__(self, url, timeout, form=None, kind="json"):
        if kind in {"pdf", "html"}:
            document_url(url, kind)
        elif url not in {"https://www.cninfo.com.cn/new/data/szse_stock.json",
                          "https://www.cninfo.com.cn/new/hisAnnouncement/query"}:
            raise ValidationError("unsupported public metadata endpoint")
        deadline = time.monotonic() + timeout
        headers = {"User-Agent": "stock-research-data/0.1", "Referer": "https://www.cninfo.com.cn/"}
        content = urllib.parse.urlencode(form).encode("utf-8") if form is not None else None
        req = urllib.request.Request(url, content, headers)
        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
                limit = 30 * 1024 * 1024 if kind == "pdf" else 8 * 1024 * 1024
                chunks, size = [], 0
                while True:
                    if time.monotonic() >= deadline:
                        raise TransientProviderError("document body deadline exceeded")
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        raise ProviderSchemaError("document response exceeds bound")
                    chunks.append(chunk)
                body = b"".join(chunks)
                content_type = response.headers.get("Content-Type", "").lower()
                if kind == "pdf" and (not body.startswith(b"%PDF") or "pdf" not in content_type):
                    raise ProviderSchemaError("source did not return a PDF")
                if kind == "html" and ("html" not in content_type or b"<html" not in body[:4096].lower()):
                    raise ProviderSchemaError("source did not return article HTML")
                return json.loads(body) if kind == "json" else body
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise ProviderAuthError("document access denied") from None
            if exc.code == 429 or exc.code >= 500:
                raise TransientProviderError("document temporary HTTP failure") from None
            raise ProviderError("document HTTP request rejected") from None
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            raise TransientProviderError("document connection failure") from None
        except (ValueError, UnicodeError):
            raise ProviderSchemaError("invalid document metadata") from None


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TransientProviderError("document provider deadline exceeded")
    return remaining


class CNInfoAnnouncementProvider:
    capability = ProviderCapability("cninfo", "p18-1", frozenset({D.ANNOUNCEMENT}),
                                    frozenset({BASES[D.ANNOUNCEMENT]}))
    def __init__(self, artifacts, transport=None, clock=utcnow, identity=None):
        self.artifacts, self.transport, self.clock = artifacts, transport or DocumentHTTPTransport(), clock
        self.identity = identity
        if identity is not None:
            from .cninfo_identity import QualifiedCNInfoIdentity
            if not isinstance(identity, QualifiedCNInfoIdentity):
                raise ValidationError('explicit reviewed identity configuration required')
            self.capability = ProviderCapability('cninfo','p18-identity-1',frozenset({D.ANNOUNCEMENT}),
                                                 frozenset({BASES[D.ANNOUNCEMENT]}))

    def fetch(self, request, scope, timeout):
        if request.dataset != D.ANNOUNCEMENT:
            raise ValidationError("unsupported CNINFO domain")
        deadline = time.monotonic() + timeout
        directory = self.transport("https://www.cninfo.com.cn/new/data/szse_stock.json", _remaining(deadline))
        if not isinstance(directory, dict) or not isinstance(directory.get("stockList"), list):
            raise ProviderSchemaError("invalid CNINFO security directory")
        matches = [r for r in directory["stockList"] if r.get("code") == request.subject.code]
        if len(matches) != 1 or not matches[0].get("orgId"):
            raise ProviderSchemaError("CNINFO subject mapping unavailable or ambiguous")
        mapping = {"code": matches[0]["code"], "orgId": matches[0]["orgId"]}
        if self.identity is not None:
            self.identity.approved(request,scope,mapping)
        form = {"pageNum": "1", "pageSize": "100", "column": "szse", "tabName": "fulltext",
                "plate": "", "stock": f"{mapping['code']},{mapping['orgId']}", "searchkey": request.selector,
                "secid": "", "category": "", "trade": "", "seDate": f"{request.start}~{request.end}",
                "sortName": "", "sortType": "", "isHLtitle": "false"}
        index_url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
        rows, total = [], None
        for page in range(1, 4):
            form["pageNum"] = str(page)
            body = self.transport(index_url, _remaining(deadline), form=dict(form))
            if not isinstance(body, dict) or type(body.get("totalAnnouncement")) is not int:
                raise ProviderSchemaError("invalid CNINFO result count")
            if body["totalAnnouncement"] > 300:
                raise ProviderSchemaError("CNINFO pagination exceeds 3 pages; narrow request")
            if total is not None and total != body["totalAnnouncement"]:
                raise ProviderSchemaError("CNINFO count changed while paginating")
            total = body["totalAnnouncement"]
            page_rows = body.get("announcements")
            if page_rows is None and total == 0:
                page_rows = []
            if not isinstance(page_rows, list) or len(page_rows) > 100:
                raise ProviderSchemaError("invalid CNINFO index page")
            for row in page_rows:
                keys = ("secCode", "announcementId", "announcementTitle", "announcementTime", "adjunctUrl")
                if not isinstance(row, dict) or not set(keys) <= row.keys():
                    raise ProviderSchemaError("CNINFO returned different subject or incomplete row")
                if self.identity is None:
                    if row['secCode'] != request.subject.code:
                        raise ProviderSchemaError('CNINFO returned different subject or incomplete row')
                else:
                    self.identity.validate(request,scope,mapping,row)
                rows.append({k: row[k] for k in keys})
            if page * 100 >= total:
                break
        if len(rows) != total:
            raise ProviderSchemaError("CNINFO index coverage changed or truncated")
        if len(rows) > 20:
            raise ProviderSchemaError("CNINFO PDF batch exceeds 20; narrow dates/title")
        prepared = []
        for row in rows:
            if type(row["announcementTime"]) is not int or not re.fullmatch(r"\d+", str(row["announcementId"])):
                raise ProviderSchemaError("invalid announcement identity or timestamp")
            period = datetime.fromtimestamp(row["announcementTime"] / 1000, SHANGHAI).date()
            title = html.unescape(re.sub(r"<[^>]*>", "", row["announcementTitle"]))
            if not request.start <= period <= request.end or (request.selector and request.selector not in title):
                raise ProviderSchemaError("CNINFO index violates date/title window")
            url = document_url("https://static.cninfo.com.cn/" + row["adjunctUrl"], "pdf")
            pdf = self.transport(url, _remaining(deadline), kind="pdf")
            if not isinstance(pdf, bytes) or not pdf.startswith(b"%PDF") or len(pdf) > 30 * 1024 * 1024:
                raise ProviderSchemaError("invalid announcement PDF bytes")
            aid = self.artifacts.put_bytes(scope, pdf)
            attrs = {"announcement_id": str(row["announcementId"]), "title": title,
                     "source_date": period.isoformat(), "pdf_artifact_id": aid,
                     "document_sha256": hashlib.sha256(pdf).hexdigest()}
            prepared.append((row, period, attrs, url))
        captured = aware(self.clock())
        index_body = {"endpoint": index_url, "subject_mapping": mapping,
                      "form": {k: v for k, v in form.items() if k != "pageNum"},
                      "total": total, "rows": rows}
        if self.identity is not None:
            index_body['identity_qualification'] = self.identity.lineage(captured)
        index = self.artifacts.put(scope,index_body)
        call = uuid.uuid4().hex
        return tuple(DomainRecord(request.subject, D.ANNOUNCEMENT, period, attrs["announcement_id"], (),
                                  tuple(attrs.items()), "cninfo", self.capability.version, url,
                                  attrs["announcement_id"], digest({"index": row, "pdf": attrs["document_sha256"],
                                      **({'identity_qualification':self.identity.approved_sha256} if self.identity else {})}),
                                  captured, captured, captured, index, call,
                                  quality_flags=("source_date_not_intraday_release", "revision_relation_not_inferred")+
                                  (("explicit_historical_code_identity",) if self.identity else ()))
                     for row, period, attrs, url in prepared)


class ArticleText(HTMLParser):
    """Extract the article's main text; sidebars do not establish company association."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.hidden, self.parts = 0, 0, []

    def handle_starttag(self, tag, attrs):
        if dict(attrs).get("id") == "ContentBody" and tag == "div":
            self.depth = 1
        elif self.depth and tag == "div":
            self.depth += 1
        if self.depth and tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if self.depth and tag == "div":
            self.depth -= 1
        if self.depth and tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if self.depth and not self.hidden:
            self.parts.append(data)


def article_text(content, source_title):
    try:
        body = content.decode("utf-8", errors="strict")
    except UnicodeError:
        raise ProviderSchemaError("article HTML encoding unsupported") from None
    titles = re.findall(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    normalize = lambda text: "".join(c for c in html.unescape(re.sub(r"<[^>]*>", "", text)) if c.isalnum())
    if not titles or not normalize(source_title) or normalize(source_title) not in normalize(titles[0]):
        raise ProviderSchemaError("original article title does not match index")
    parser = ArticleText()
    parser.feed(body)
    text = " ".join(parser.parts)
    if not text.strip():
        raise ProviderSchemaError("article main content unavailable")
    return text


class AkShareNewsProvider:
    capability = ProviderCapability("akshare", "p18-2", frozenset({D.NEWS}), frozenset({BASES[D.NEWS]}))
    def __init__(self, artifacts, transport=None, documents=None, clock=utcnow):
        self.artifacts, self.transport = artifacts, transport or AkShareSubprocessTransport()
        self.documents, self.clock = documents or DocumentHTTPTransport(), clock

    def fetch(self, request, scope, timeout):
        if request.dataset != D.NEWS:
            raise ValidationError("unsupported AKShare news domain")
        deadline = time.monotonic() + timeout
        names = self.transport("stock_info_a_code_name", {}, min(120, _remaining(deadline)))
        if (not isinstance(names, dict) or names.get("columns") != ["code", "name"]
                or not isinstance(names.get("rows"), list)):
            raise ProviderSchemaError("current company-name mapping unavailable")
        matched = [r for r in names["rows"] if isinstance(r, list) and len(r) == 2 and r[0] == request.subject.code]
        if len(matched) != 1 or not isinstance(matched[0][1], str) or not matched[0][1]:
            raise ProviderSchemaError("current news subject name is missing or ambiguous")
        company_name = matched[0][1]
        body = self.transport("stock_news_em", {"symbol": request.subject.code}, min(120, _remaining(deadline)))
        fields = ("关键词", "新闻标题", "新闻内容", "发布时间", "文章来源", "新闻链接")
        if (not isinstance(body, dict) or not isinstance(body.get("columns"), list)
                or set(body["columns"]) != set(fields) or len(body["columns"]) != len(fields)
                or not isinstance(body.get("rows"), list) or len(body["rows"]) > 100):
            raise ProviderSchemaError("invalid AKShare recent news table")
        prepared, excluded = [], []
        for item in body["rows"]:
            if not isinstance(item, list) or len(item) != len(fields):
                raise ProviderSchemaError("news row length mismatch")
            row = dict(zip(body["columns"], item))
            if any(not isinstance(row[f], str) for f in fields) or row["关键词"] != request.subject.code:
                raise ProviderSchemaError("invalid news metadata or different keyword")
            try:
                shown = datetime.fromisoformat(row["发布时间"])
                shown = shown.replace(tzinfo=SHANGHAI) if shown.tzinfo is None else shown.astimezone(SHANGHAI)
            except ValueError:
                raise ProviderSchemaError("invalid news source timestamp") from None
            if not request.start <= shown.date() <= request.end:
                continue
            # AKShare constructs HTTP article links. Fetch only the matching fixed HTTPS origin.
            original = row["新闻链接"]
            url = document_url(original.replace("http://finance.eastmoney.com/", "https://finance.eastmoney.com/", 1), "html")
            article = self.documents(url, _remaining(deadline), kind="html")
            if not isinstance(article, bytes) or len(article) > 8 * 1024 * 1024:
                raise ProviderSchemaError("invalid article bytes")
            main_text = article_text(article, row["新闻标题"])
            explicit_code = re.search(r"(?<!\d)" + re.escape(request.subject.provider_symbol) + r"(?![A-Za-z0-9_])", main_text)
            if company_name not in main_text and company_name not in row["新闻标题"] and not explicit_code:
                excluded.append({"url": url, "reason": "keyword_match_without_confirmed_company_mention"})
                continue
            article_id = self.artifacts.put_bytes(scope, article)
            attrs = {"title": row["新闻标题"], "snippet": row["新闻内容"], "publisher": row["文章来源"],
                     "source_time": shown.isoformat(), "body_artifact_id": article_id, "body_kind": "original_html",
                     "company_name": company_name, "association_basis": "current_company_name_or_qualified_code_in_article"}
            prepared.append((row, shown, attrs, url))
        captured = aware(self.clock())
        if any(shown > captured for _, shown, *_ in prepared):
            raise ProviderSchemaError("news claims a future publication time")
        table = self.artifacts.put(scope, {"endpoint": "stock_news_em", "symbol": request.subject.code,
                                          "akshare_version": body.get("version"), "columns": body["columns"],
                                          "rows": body["rows"], "current_company_mapping": matched[0],
                                          "excluded_rows": excluded})
        call = uuid.uuid4().hex
        return tuple(DomainRecord(request.subject, D.NEWS, shown.date(), url, (), tuple(attrs.items()),
                                  "akshare", self.capability.version, url, url,
                                  digest({"row": row, "html": attrs["body_artifact_id"]}), captured, captured,
                                  captured, table, call, quality_flags=("recent_list_coverage_not_verified",
                                  "publisher_timestamp_not_verified", "akshare_parsed_table_not_raw_http",
                                  "company_mention_does_not_imply_exclusive_subject"))
                     for row, shown, attrs, url in prepared)
