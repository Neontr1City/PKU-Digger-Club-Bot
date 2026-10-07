from html.parser import HTMLParser

from cricket import create_app, db, enrichment, service


class FormInputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        if tag == 'input':
            values = dict(attrs)
            if values.get('name'):
                self.values[values['name']] = values.get('value', '')


def candidate(provider, id_, **changes):
    is_apple = provider == 'itunes'
    row = dict(
        provider=provider,
        id=id_,
        artist='Oasis',
        title='Stand by Me',
        album='Be Here Now',
        artist_id=f'{provider}:1',
        duration=357,
        date='1997-08-21',
        region='US' if is_apple else '网易云',
        source=(
            f'https://music.apple.com/us/song/{id_}'
            if is_apple
            else f'https://music.163.com/song?id={id_}'
        ),
        artwork='',
        artwork_source='',
        disambiguation='',
    )
    row.update(changes)
    return row


def test_candidate_list_is_bounded_and_keeps_cn_results():
    original = dict(artist='Oasis', title='Stand by Me')
    rows = [candidate('itunes', str(i)) for i in range(30)]
    rows += [candidate('itunes', 'cn', region='CN', source='https://music.apple.com/cn/song/cn')]
    rows += [candidate('netease', str(i)) for i in range(25)]
    rows += [candidate('musicbrainz', str(i)) for i in range(12)]
    choices = enrichment.evidence_candidates(original, rows)
    assert len(choices) == 50
    assert choices[0]['id'] == 'cn'
    assert [c['provider'] for c in choices].count('itunes') == 20
    assert [c['provider'] for c in choices].count('netease') == 20
    assert [c['provider'] for c in choices].count('musicbrainz') == 10


def test_candidate_draft_requires_a_trusted_listening_source():
    row = candidate(
        'netease',
        '17',
        artwork='https://p1.music.126.net/cover.jpg',
        artwork_source='https://music.163.com/album?id=4',
    )
    draft = enrichment.candidate_draft(row)
    assert draft['netease'] == row['source']
    assert draft['apple'] == ''
    assert draft['sources'] == [row['source'], row['artwork_source']]
    assert draft['artwork'] == row['artwork']
    assert enrichment.candidate_draft(dict(row, source='https://example.org/song/17')) is None
    assert enrichment.candidate_draft(candidate('musicbrainz', '17')) is None


def test_picker_appears_only_after_manual_review_and_fills_form(tmp_path):
    app = create_app(
        dict(
            TESTING=True,
            DATABASE=str(tmp_path / 'candidate-review.sqlite3'),
            SECRET_KEY='test-only',
            ADMIN_PASSWORD='test-only',
        )
    )
    client = app.test_client()
    with db.connect(app.config['DATABASE']) as conn:
        service.nominate(
            conn,
            dict(
                submission_id='b' * 32,
                nominator='示例听众',
                a_artist='Oasis',
                a_title='Stand By Me',
                b_artist='The Smiths',
                b_title='There Is a Light That Never Goes Out',
            ),
        )
        nomination_id = conn.execute('SELECT id FROM nominations').fetchone()['id']
        selected = candidate(
            'netease',
            '17',
            artwork='https://p1.music.126.net/cover.jpg',
            artwork_source='https://music.163.com/album?id=4',
        )
        alternative = candidate(
            'itunes',
            '18',
            region='CN',
            source='https://music.apple.com/cn/song/18',
        )
        other_track = dict(
            artist='The Smiths',
            title='There Is a Light That Never Goes Out',
            album='The Queen Is Dead',
            artist_id='apple:2',
            apple='https://music.apple.com/cn/song/2',
            netease='',
            artwork='',
            artwork_source='',
            sources=['https://music.apple.com/cn/song/2'],
            version='',
        )
        side_a = dict(
            resolved=False,
            track=None,
            candidates=[selected, alternative],
            corrections=[],
            reasons=['同名艺人身份不确定'],
            warnings=[],
            queries=[],
        )
        side_b = dict(
            resolved=True,
            track=other_track,
            candidates=[candidate('itunes', '19')],
            corrections=[],
            reasons=[],
            warnings=[],
            queries=[],
        )
        report = dict(
            rule_version='test',
            checked_at=service.stamp(service.utcnow()),
            attempt=1,
            sides={'a': side_a, 'b': side_b},
        )
        conn.execute(
            "UPDATE enrichment_jobs SET status='queued', report=? WHERE nomination_id=?",
            (service.encode(report), nomination_id),
        )
    client.get('/admin/login')
    with client.session_transaction() as session:
        csrf = session['csrf']
    assert (
        client.post('/admin/login', data={'csrf': csrf, 'password': 'test-only'}).status_code == 303
    )
    with client.session_transaction() as session:
        csrf = session['csrf']
    url = f'/admin/nomination/{nomination_id}'
    assert '从已找到的候选中选择' not in client.get(url).get_data(as_text=True)

    with db.connect(app.config['DATABASE']) as conn:
        conn.execute(
            "UPDATE enrichment_jobs SET status='error' WHERE nomination_id=?",
            (nomination_id,),
        )
    assert '从已找到的候选中选择' not in client.get(url).get_data(as_text=True)

    with db.connect(app.config['DATABASE']) as conn:
        conn.execute(
            "UPDATE enrichment_jobs SET status='review' WHERE nomination_id=?",
            (nomination_id,),
        )
    page = client.get(url).get_data(as_text=True)
    assert '从已找到的候选中选择' in page
    assert '2 个可选曲目' in page
    assert '1 个可选曲目' in page
    assert '打开来源 ↗' in page

    selected_page = client.get(url + '?a_candidate=0').get_data(as_text=True)
    fields = FormInputs()
    fields.feed(selected_page)
    assert fields.values['a_artist'] == 'Oasis'
    assert fields.values['a_title'] == 'Stand by Me'
    assert fields.values['a_album'] == 'Be Here Now'
    assert fields.values['a_netease'] == selected['source']
    assert fields.values['b_apple'] == other_track['apple']
    assert 'a_candidate=0&amp;b_candidate=0' in selected_page
    assert '已选择' in selected_page

    invalid = client.get(url + '?a_candidate=999').get_data(as_text=True)
    fields = FormInputs()
    fields.feed(invalid)
    assert fields.values['a_netease'] == ''
    draft = enrichment.candidate_draft(selected)
    form = {'csrf': csrf, 'verified': '1'}
    for side, track in (('a', draft), ('b', other_track)):
        for key in (
            'artist',
            'title',
            'album',
            'artist_id',
            'version',
            'netease',
            'apple',
            'artwork',
            'artwork_source',
        ):
            form[f'{side}_{key}'] = track.get(key, '')
        form[f'{side}_sources'] = '\n'.join(track['sources'])
    assert client.post(url, data=form).status_code == 303
    with db.connect(app.config['DATABASE']) as conn:
        saved = service.unpack(conn.execute('SELECT * FROM nominations').fetchone())
    assert saved['status'] == 'ready'
    assert saved['a']['netease'] == selected['source']
    assert '从已找到的候选中选择' not in client.get(url).get_data(as_text=True)
