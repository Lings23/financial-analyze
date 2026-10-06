"""Operator-reviewed, SHA-pinned identity proofs for explicit CNINFO requests.

This never infers aliases from a directory orgId or from the last code digits.
Proofs are current observations, not historical availability qualifications.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re

from ..domains import DomainDataset
from ..errors import ProviderSchemaError, ValidationError
from ..models import aware

TABLE = 'https://www.bse.cn/service/code_mapping.html'
GENERAL = 'https://www.bse.cn/important_news/200026735.html'
MEMBERS = 'https://www.bse.cn/important_news/200025487.html'
PILOT = 'https://www.bse.cn/important_news/200025603.html'
STATEMENTS = {
    GENERAL: '自2025年10月9日起，本所将为存量股票启用新证券代码',
    MEMBERS: '确定颖泰生物、艾融软件、龙竹科技、佳先股份、同享科技、球冠电缆6只股票进行试点切换',
    PILOT: '自2025年5月6日起，本所为试点股票启用新证券代码',
}
PILOT_NAMES = frozenset(('颖泰生物','艾融软件','龙竹科技','佳先股份','同享科技','球冠电缆'))
SHANGHAI = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class QualifiedCNInfoIdentity:
    """Trusted configuration; constructors require an independently approved hash."""
    manifest_bytes: bytes
    approved_sha256: str

    def __post_init__(self):
        if (not isinstance(self.manifest_bytes, bytes) or len(self.manifest_bytes) > 65536
                or not isinstance(self.approved_sha256,str)
                or not re.fullmatch(r'[0-9a-f]{64}',self.approved_sha256)
                or hashlib.sha256(self.manifest_bytes).hexdigest() != self.approved_sha256):
            raise ValidationError('identity qualification hash or bound invalid')
        try:
            doc = json.loads(self.manifest_bytes)
            if doc['schema'] != 'cninfo-qualified-identity-v1' or not isinstance(doc['scope'],str) or not doc['scope']:
                raise ValidationError('identity qualification schema invalid')
            proofs = doc['proofs']
            if not isinstance(proofs,list) or len(proofs) != 4:
                raise ValidationError('four reviewed identity proof projections required')
            by_url = {p['url']:p for p in proofs}
            if set(by_url) != {TABLE, GENERAL, MEMBERS, PILOT}:
                raise ValidationError('identity proof origins or uniqueness invalid')
            for p in proofs:
                if p['evidence_kind'] != 'rendered_official_dom_projection':
                    raise ValidationError('identity proof observation type unsupported')
                aware(datetime.fromisoformat(p['observed_at']))
            for url, statement in STATEMENTS.items():
                if by_url[url]['statement'] != statement:
                    raise ValidationError('identity switch evidence inconsistent')
            table = by_url[TABLE]
            if table['header'] != ['序号','证券简称','上市日期','旧代码','新代码']:
                raise ValidationError('identity mapping table header invalid')
            rows = table['rows']
            if not isinstance(rows,list) or not 1 <= len(rows) <= 20:
                raise ValidationError('identity proof row bound invalid')
            mapping = {}
            for row in rows:
                if (not isinstance(row,list) or len(row)!=5 or not all(isinstance(v,str) for v in row)
                        or not re.fullmatch(r'\d{6}',row[3]) or not re.fullmatch(r'920\d{3}',row[4])
                        or row[3] == row[4] or row[4] in mapping):
                    raise ValidationError('identity proof row invalid or ambiguous')
                mapping[row[4]] = row
            requests = doc['approved_requests']
            if not isinstance(requests,list) or not 1 <= len(requests) <= 20:
                raise ValidationError('explicit bounded identity requests required')
            keys = set()
            for item in requests:
                row = mapping[item['code']]
                cutover = date(2025,5,6) if row[1] in PILOT_NAMES else date(2025,10,9)
                start, end = date.fromisoformat(item['start_date']), date.fromisoformat(item['end_date'])
                key = (item['code'],item['start_date'],item['end_date'],item['selector'])
                if (item['old_code'] != row[3] or date.fromisoformat(item['cutover_date']) != cutover
                        or not start <= end < cutover or key in keys
                        or not isinstance(item['org_id'],str) or not item['org_id']
                        or not isinstance(item['selector'],str) or not item['selector']):
                    raise ValidationError('identity request qualification inconsistent')
                keys.add(key)
        except (KeyError,TypeError,ValueError,UnicodeError):
            raise ValidationError('invalid reviewed identity qualification') from None

    @property
    def document(self):
        # Decode a fresh copy so consumers cannot mutate the frozen qualification.
        return json.loads(self.manifest_bytes)

    @property
    def observed_at(self):
        return max(aware(datetime.fromisoformat(p['observed_at'])) for p in self.document['proofs'])

    def approved(self, request, scope, directory_mapping):
        doc = self.document
        if (scope != doc['scope'] or request.dataset != DomainDataset.ANNOUNCEMENT
                or request.subject.kind != 'equity' or request.subject.exchange != 'BSE'):
            raise ProviderSchemaError('identity qualification request or scope mismatch')
        matches = [q for q in doc['approved_requests'] if
                   (q['code'],q['start_date'],q['end_date'],q['selector']) ==
                   (request.subject.code,request.start.isoformat(),request.end.isoformat(),request.selector)]
        if len(matches) != 1:
            raise ProviderSchemaError('CNINFO identity request not explicitly qualified')
        q = matches[0]
        if directory_mapping != {'code':q['code'],'orgId':q['org_id']}:
            raise ProviderSchemaError('CNINFO directory identity differs from qualification')
        return q

    def validate(self, request, scope, directory_mapping, row):
        q = self.approved(request,scope,directory_mapping)
        if type(row.get('announcementTime')) is not int or not isinstance(row.get('secCode'),str):
            raise ProviderSchemaError('identity source timestamp invalid')
        try:
            day = datetime.fromtimestamp(row['announcementTime']/1000,SHANGHAI).date()
        except (ValueError,OverflowError,OSError):
            raise ProviderSchemaError('identity source timestamp invalid') from None
        if (not request.start <= day <= request.end
                or row.get('secCode') not in {q['code'],q['old_code']}
                or (row['secCode']==q['old_code'] and day >= date.fromisoformat(q['cutover_date']))):
            raise ProviderSchemaError('CNINFO source code or effective date not qualified')

    def lineage(self, captured):
        if aware(captured) < self.observed_at:
            raise ProviderSchemaError('identity evidence was observed after capture')
        return {'sha256':self.approved_sha256,'reviewed_manifest_utf8':self.manifest_bytes.decode('utf8'),
                'availability_not_upgraded':True}
