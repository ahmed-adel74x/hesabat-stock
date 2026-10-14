"""قائمة منسدلة قابلة للكتابة والبحث (نفس منطق logic.search: عربي، كل الكلمات، وبالرقم لو by_number)."""
from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtWidgets import QCompleter, QComboBox

from ..logic.search import first_match, matches, normalize


class _Filter(QSortFilterProxyModel):
    """بيفلتر اقتراحات الكتابة بس. القائمة الكاملة (السهم) مبتتأثرش بيه."""

    def __init__(self, parent, by_number):
        super().__init__(parent)
        self._query, self._by_number = "", by_number

    def set_query(self, text):
        self._query = text or ""
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        m = self.sourceModel()
        idx = m.index(row, 0, parent)
        number = m.data(idx, Qt.ItemDataRole.UserRole) if self._by_number else None
        return matches(self._query, m.data(idx, Qt.ItemDataRole.DisplayRole), number)


class SearchCombo(QComboBox):
    """اكتب جزء من الاسم (أو رقمه لو by_number) فتظهر الاقتراحات، واختار منها. السهم بيفتح القائمة كلها.

    القراءة: استخدم value() مش currentData(). بترجع None لو النص المكتوب مش مطابق لعنصر،
    عشان مياخدش العنصر القديم بالغلط. Enter أو الخروج من الخانة بيختار أول عنصر مطابق."""

    def __init__(self, by_number=False, placeholder="اكتب للبحث..."):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._by_number = by_number
        self._filter = _Filter(self, by_number)
        self._filter.setSourceModel(self.model())
        completer = QCompleter(self._filter, self)
        completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        edit = self.lineEdit()
        edit.setCompleter(completer)      # على الخانة مباشرة (مش combo.setCompleter) عشان الاختيار يمشي بالاسم مش بترتيب الصف
        edit.setPlaceholderText(placeholder)
        edit.textEdited.connect(self._filter.set_query)
        edit.editingFinished.connect(self.resolve)
        completer.activated[str].connect(self._pick)

    def _pick(self, text):
        i = self.findText(text)
        if i >= 0:
            self.setCurrentIndex(i)
            self.setEditText(self.itemText(i))

    def is_valid(self):
        i = self.currentIndex()
        return i >= 0 and normalize(self.currentText()) == normalize(self.itemText(i))

    def resolve(self, *args):
        """لو المكتوب مش هو العنصر الحالي: اختار أول عنصر مطابق. لو مفيش مطابق سيب النص (هيبقى غير صالح)."""
        if self.is_valid():
            return
        items = [(self.itemText(i), self.itemData(i) if self._by_number else None) for i in range(self.count())]
        i = first_match(self.currentText(), items)
        if i is not None:
            self.setCurrentIndex(i)
            self.setEditText(self.itemText(i))

    def value(self):
        self.resolve()
        return self.currentData() if self.is_valid() else None
