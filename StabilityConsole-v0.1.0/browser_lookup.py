"""Visible installed-browser lookup. No login, submissions or CAPTCHA bypass."""
from __future__ import annotations
import html
import ipaddress
import json
import re
import socket
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse, urlencode, parse_qs, urljoin
from mail_sync import normal


def public_url(value):
    try:
        p = urlparse(value)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443): return ''
        if p.hostname == 'localhost' or '.' not in p.hostname or p.hostname.endswith(('.local', '.internal', '.localhost')): return ''
        try:
            if not ipaddress.ip_address(p.hostname).is_global: return ''
        except ValueError: pass
        if re.search(r'unsubscribe|sign.?in|log.?in|oauth|/auth|interview|onboarding|/accept|/confirm|/verify|/apply(?:/|$)', p.path, re.I): return ''
        if any(re.search(r'token|secret|password|signature|authorization|session|email|^code$|^key$|^ticket$|jwt', key, re.I) for key in parse_qs(p.query)): return ''
        return p._replace(fragment='').geturl()
    except (ValueError, TypeError): return ''


def nodes(value):
    out = []
    if isinstance(value, list):
        for v in value: out.extend(nodes(v))
    elif isinstance(value, dict):
        if 'JobPosting' in ([value.get('@type')] if isinstance(value.get('@type'), str) else (value.get('@type') or [])): out.append(value)
        for v in value.values():
            if isinstance(v, (list, dict)): out.extend(nodes(v))
    return out


def plain(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', str(value or '')))).strip()


def structured_proposal(job, source, application, message):
    """Require exact normalized title and independent corroboration for auto-fill."""
    title, employer = plain(job.get('title')), plain((job.get('hiringOrganization') or {}).get('name'))
    if normal(title) != normal(application['title']): return None
    existing = normal(application.get('employer', ''))
    mail = normal(message.get('subject', '') + ' ' + message.get('body', ''))
    source_org = (job.get('hiringOrganization') or {}).get('url', '')
    from email.utils import parseaddr
    sender_domain = parseaddr(message.get('sender', ''))[1].partition('@')[2].casefold()
    org_host = (urlparse(source_org).hostname or '').casefold()
    employer_match = bool(employer and (existing == normal(employer) or (len(normal(employer)) >= 4 and normal(employer) in mail)))
    domain_match = bool(sender_domain and org_host and (org_host == sender_domain or org_host.endswith('.' + sender_domain)))
    conflict = bool(existing and normal(employer) != existing)
    locations = []
    location_value = job.get('jobLocation') or []
    for loc in location_value if isinstance(location_value, list) else [location_value]:
        address = loc.get('address') or {}
        if isinstance(address, str): locations.append(plain(address)); continue
        country = address.get('addressCountry')
        if isinstance(country, dict): country = country.get('name')
        location = ', '.join(plain(address.get(k)) for k in ('streetAddress','addressLocality','addressRegion') if address.get(k))
        if country: location += (', ' if location else '') + plain(country)
        if location: locations.append(location)
    closing = plain(job.get('validThrough'))
    expired = False
    try:
        dt = datetime.fromisoformat(closing.replace('Z', '+00:00'))
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        expired = dt < datetime.now(timezone.utc)
    except ValueError: pass
    described=plain(job.get('description')).lower()
    explicit_close=re.search(r'(?:closing\s*(?:date|dtae)|applications?\s+close(?:s)?)\s*[:\-–]?\s*(\d{1,2}\s+[a-z]+\s+\d{4})',described)
    if explicit_close:
        try:
            dt=datetime.strptime(explicit_close[1],'%d %B %Y').replace(tzinfo=timezone.utc)
            if dt < datetime.now(timezone.utc): expired=True
        except ValueError: conflict=True
    if application.get('area') and locations and normal(application['area']) not in normal(' '.join(locations)):
        conflict = True
    values = {'employer': employer, 'area': ' / '.join(locations), 'url': source}
    pay = job.get('baseSalary')
    details = {'title': title, 'employer': employer or 'UNKNOWN', 'location': values['area'] or 'UNKNOWN',
               'salary': plain(json.dumps(pay)) if pay else 'UNKNOWN',
               'work_arrangement': 'Remote' if job.get('jobLocationType') == 'TELECOMMUTE' else 'UNKNOWN',
               'employment_type': job.get('employmentType') or 'UNKNOWN', 'posted': job.get('datePosted') or 'UNKNOWN',
               'closing': closing or 'UNKNOWN', 'requirements': plain(job.get('qualifications') or job.get('description'))[:20000] or 'UNKNOWN'}
    return {'source': source, 'checked_at': datetime.now(timezone.utc).isoformat(), 'values': values, 'details': details,
            'auto_eligible': bool((employer_match or domain_match) and not conflict and not expired),
            'evidence': 'Exact title match; ' + ('employer corroborated by existing entry/email' if employer_match else 'sender and hiring organisation domain match' if domain_match else 'employer not corroborated') + ('; conflicting entered employer/location' if conflict else '') + ('; source closing date has passed' if expired else '')}


def choose_proposal(proposals):
    # Syndicated copies with identical title, employer and location form one candidate, preserving all sources.
    groups = {}
    for p in proposals:
        key = tuple(normal(p['details'].get(k,'')) for k in ('title','employer','location'))
        groups.setdefault(key, []).append(p)
    if len(groups) != 1:
        return {'state': 'AMBIGUOUS' if groups else 'UNKNOWN', 'candidates': proposals,
                'message': 'Several different adverts match the title. Review before filling.' if groups else 'No individually structured matching advert was found. Nothing filled.'}
    group = next(iter(groups.values()))
    chosen = next((p for p in group if p['auto_eligible']), group[0])
    chosen['sources'] = [p['source'] for p in group]
    return {'state': 'CORROBORATED' if chosen['auto_eligible'] else 'REVIEW', 'proposal': chosen, 'candidates': proposals,
            'message': chosen['evidence']}


def lookup(payload):
    from playwright.sync_api import sync_playwright
    app, message = payload['application'], payload['message']
    channel = payload.get('browser', 'msedge')
    if channel not in ('msedge','chrome'): raise ValueError('Select installed Edge or Chrome.')
    checked_hosts = {}
    def check_host(host):
        if host not in checked_hosts:
            try:
                addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
                checked_hosts[host] = bool(addresses) and all(ipaddress.ip_address(a[4][0]).is_global for a in addresses)
            except OSError: checked_hosts[host] = False
        return checked_hosts[host]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=channel, headless=False, timeout=15000)
        try:
            context = browser.new_context(accept_downloads=False)
            def route_request(route):
                u = urlparse(route.request.url)
                if u.scheme in ('data', 'blob'): route.continue_(); return
                if u.scheme != 'https' or not u.hostname or not check_host(u.hostname): route.abort(); return
                if route.request.method not in ('GET','HEAD'): route.abort(); return
                route.continue_()
            context.route('**/*', route_request)
            page = context.new_page(); page.set_default_timeout(5000); page.set_default_navigation_timeout(20000)
            proposals, failures, inspected = [], [], set()
            direct=[]
            for link in message.get('links', []):
                url=public_url(link)
                if url and re.search(r'job|career|vacan|position|adverts',urlparse(url).path,re.I):direct.append(url)
            direct=list(dict.fromkeys(direct))
            query=' '.join(x for x in ('"'+app['title']+'"',app.get('employer',''),app.get('area',''),'job vacancy') if x)
            search_url='https://www.google.com/search?'+urlencode({'q':query})
            def inspect(urls):
                for url in list(dict.fromkeys(urls)):
                    if url in inspected:continue
                    if len(inspected)>=5:return
                    inspected.add(url)
                    try:
                        response=page.goto(url,wait_until='domcontentloaded')
                        if response and response.status>=400:
                            failures.append('Advert HTTP '+str(response.status));continue
                        visible=page.locator('body').inner_text(timeout=5000)
                        if re.search(r'verify (?:that )?you are human|unusual traffic|checking your browser|automated queries|not a robot',visible,re.I):
                            failures.append('Advert requires human verification; no bypass attempted');continue
                        final=public_url(page.url)
                        if not final:failures.append('Advert redirected to an unsupported/private action page');continue
                        for raw in page.locator('script[type="application/ld+json"]').all_text_contents():
                            if len(raw)>1000000:continue
                            try:jobs=nodes(json.loads(raw))
                            except (ValueError,TypeError):continue
                            for job in jobs:
                                proposal=structured_proposal(job,final,app,message)
                                if proposal:
                                    proposal['direct_email_link']=url in direct
                                    proposals.append(proposal)
                    except Exception:failures.append('Advert timed out or could not be inspected')
            def finish(search_state):
                result=choose_proposal(proposals)
                result.update(search_url=search_url,search_state=search_state,failures=failures,inspected_limit=5,inspected_count=len(inspected))
                if failures and result['state']=='CORROBORATED':
                    result['state']='REVIEW';result['proposal']['auto_eligible']=False
                    result['message']+='; incomplete source checks — review required'
                return result
            # Email-linked public advert is stronger identity evidence than a title search.
            inspect(direct)
            if len(direct)>5:failures.append('More than five email advert links; inspection budget reached')
            initial=finish('Not needed: inspected email-linked advert')
            if initial['state'] in ('CORROBORATED','AMBIGUOUS'):
                return initial
            candidates=[]
            search_state='DISCOVERED'
            try:
                page.goto(search_url,wait_until='domcontentloaded')
                visible=page.locator('body').inner_text(timeout=5000)
                if re.search(r'unusual traffic|verify (?:that )?you are human|automated queries|not a robot|checking your browser',visible,re.I):
                    failures.append('Google requires human verification. Search stopped; no bypass attempted.');search_state='BLOCKED'
                elif 'consent.google.' in page.url:
                    failures.append('Search requires a consent decision. Use the regular browser to review it.');search_state='BLOCKED'
                else:
                    page.locator('#search h3').first.wait_for(state='visible',timeout=8000)
                    for anchor in page.locator('#search a:has(h3)').all()[:8]:
                        href=anchor.get_attribute('href') or ''
                        if href.startswith('/url?'):href=parse_qs(urlparse(href).query).get('q',[''])[0]
                        url=public_url(href)
                        if url and not (urlparse(url).hostname or '').endswith('google.com'):candidates.append(url)
            except Exception:
                failures.append('Search layout, network or access failure; no search results confirmed');search_state='FAILED'
            inspect(candidates)
            if len(set(direct+candidates)-inspected)>0:
                failures.append('Candidate pages remain uninspected beyond the five-page budget; uniqueness is uncertain')
            result=finish(search_state)
            if not proposals and search_state in ('BLOCKED','FAILED'):
                result['state']=search_state;result['message']='Web discovery could not complete. Nothing filled; inspect source failures and use Open public web search.'
            return result
        finally:
            browser.close()


if __name__ == '__main__':
    try:
        raw = sys.stdin.read(150001)
        if len(raw) > 150000: raise ValueError('Lookup input too large.')
        result = lookup(json.loads(raw))
    except Exception:
        result = {'state':'FAILED','message':'Browser lookup could not run. Install integration support and the selected Edge/Chrome browser. Browser policies, layout changes or access restrictions may also block lookup. Nothing filled.'}
    print(json.dumps(result))
