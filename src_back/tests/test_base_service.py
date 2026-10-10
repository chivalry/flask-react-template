from src_back.services.base import ChildRecordService, CRUDService
from src_back.tests.conftest import Widget, WidgetNote


def _make_widget(db, name='alpha'):
    widget = Widget(name=name)
    db.session.add(widget)
    db.session.commit()
    return widget


def _make_note(db, widget, body='note'):
    note = WidgetNote(widget_id=widget.id, body=body)
    db.session.add(note)
    db.session.commit()
    return note


class RecordingCRUDService(CRUDService[Widget]):
    def __init__(self):
        super().__init__(Widget, Widget.name)
        self.deleted = []

    def before_delete(self, record):
        self.deleted.append(record.name)


class RecordingChildService(ChildRecordService[WidgetNote]):
    def __init__(self):
        super().__init__(WidgetNote, 'widget_id', WidgetNote.id)
        self.deleted = []

    def before_delete(self, record):
        self.deleted.append(record.body)


# -- CRUDService --------------------------------------------------------------


def test_crud_list_applies_default_ordering(db):
    _make_widget(db, 'beta')
    _make_widget(db, 'alpha')
    names = [w.name for w in CRUDService(Widget, Widget.name).list()]
    assert names == ['alpha', 'beta']


def test_crud_list_filters_by_columns(db):
    _make_widget(db, 'alpha')
    _make_widget(db, 'beta')
    names = [w.name for w in CRUDService(Widget, Widget.name).list(name='beta')]
    assert names == ['beta']


def test_crud_get_returns_record_or_none(db):
    widget = _make_widget(db)
    service = CRUDService(Widget, Widget.name)
    assert service.get(widget.id) is widget
    assert service.get(widget.id + 1) is None


def test_crud_create_persists_data_and_extra_columns(db):
    service = CRUDService(Widget, Widget.name)
    created = service.create({}, name='gamma')
    assert created.id is not None
    assert db.session.get(Widget, created.id).name == 'gamma'
    assert service.create({'name': 'delta'}).name == 'delta'


def test_crud_create_lets_explicit_keywords_win_over_body_values(db):
    service = CRUDService(Widget, Widget.name)
    created = service.create({'name': 'from-body'}, name='from-caller')
    assert created.name == 'from-caller'


def test_crud_update_sets_fields_and_returns_record(db):
    widget = _make_widget(db)
    updated = CRUDService(Widget, Widget.name).update(widget.id, {'name': 'renamed'})
    assert updated is widget
    assert db.session.get(Widget, widget.id).name == 'renamed'


def test_crud_update_returns_none_for_missing_record(db):
    assert CRUDService(Widget, Widget.name).update(999, {'name': 'x'}) is None


def test_crud_delete_calls_hook_and_removes_record(db):
    widget = _make_widget(db)
    service = RecordingCRUDService()
    assert service.delete(widget.id) is True
    assert service.deleted == ['alpha']
    assert db.session.get(Widget, widget.id) is None


def test_crud_delete_returns_false_for_missing_record(db):
    service = RecordingCRUDService()
    assert service.delete(999) is False
    assert service.deleted == []


def test_crud_default_before_delete_is_a_no_op(db):
    widget = _make_widget(db)
    assert CRUDService(Widget, Widget.name).before_delete(widget) is None


# -- ChildRecordService -------------------------------------------------------


def test_child_list_returns_only_the_parents_records(db):
    first, second = _make_widget(db, 'first'), _make_widget(db, 'second')
    _make_note(db, first, 'one')
    _make_note(db, second, 'two')
    _make_note(db, first, 'three')
    service = ChildRecordService(WidgetNote, 'widget_id', WidgetNote.id)
    assert [n.body for n in service.list(first.id)] == ['one', 'three']


def test_child_get_returns_record_or_none(db):
    note = _make_note(db, _make_widget(db))
    service = ChildRecordService(WidgetNote, 'widget_id', WidgetNote.id)
    assert service.get(note.id) is note
    assert service.get(note.id + 1) is None


def test_child_get_for_parent_enforces_ownership(db):
    owner, other = _make_widget(db, 'owner'), _make_widget(db, 'other')
    note = _make_note(db, owner)
    service = ChildRecordService(WidgetNote, 'widget_id', WidgetNote.id)
    assert service.get_for_parent(note.id, owner.id) is note
    assert service.get_for_parent(note.id, other.id) is None
    assert service.get_for_parent(note.id + 1, owner.id) is None


def test_child_create_links_the_parent_and_extra_columns(db):
    widget = _make_widget(db)
    service = ChildRecordService(WidgetNote, 'widget_id', WidgetNote.id)
    created = service.create(widget.id, {}, body='extra')
    assert created.widget_id == widget.id
    assert created.body == 'extra'
    assert service.create(widget.id, {'body': 'data'}).body == 'data'


def test_child_create_url_parent_wins_over_parent_id_in_body(db):
    owner, other = _make_widget(db, 'owner'), _make_widget(db, 'other')
    service = ChildRecordService(WidgetNote, 'widget_id', WidgetNote.id)
    created = service.create(owner.id, {'widget_id': other.id, 'body': 'routed'})
    assert created.widget_id == owner.id
    assert created.body == 'routed'


def test_child_update_sets_fields_on_the_given_record(db):
    note = _make_note(db, _make_widget(db))
    service = ChildRecordService(WidgetNote, 'widget_id', WidgetNote.id)
    assert service.update(note, {'body': 'changed'}) is note
    assert db.session.get(WidgetNote, note.id).body == 'changed'


def test_child_delete_calls_hook_and_removes_record(db):
    note = _make_note(db, _make_widget(db), 'doomed')
    service = RecordingChildService()
    service.delete(note)
    assert service.deleted == ['doomed']
    assert db.session.get(WidgetNote, note.id) is None


def test_child_default_before_delete_is_a_no_op(db):
    note = _make_note(db, _make_widget(db))
    service = ChildRecordService(WidgetNote, 'widget_id', WidgetNote.id)
    assert service.before_delete(note) is None
