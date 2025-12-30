class RowPacker(object):
    def __call__(self, row):
        raise NotImplementedError


class DefaultPacker(RowPacker):
    def __call__(self, row):
        return row.to_dict()


class ExtFieldsPacker(RowPacker):
    def __init__(self, ext_field_names, defaults=None):
        self._ext_field_names = ext_field_names
        self._defaults = defaults or {}

    def update_fields(self, *args, **kwargs):
        self._ext_field_names.extend(args)
        self._defaults.update(kwargs)

    def __call__(self, items_in_row):
        assert len(self._ext_field_names) == len(items_in_row) - 1
        data = items_in_row[0].to_dict()
        for idx, name in enumerate(self._ext_field_names):
            data[name] = items_in_row[idx + 1] or self._defaults.get(name)
        return data


class Pagination(object):
    MAX_PAGE_SIZE = 1000

    def __init__(self, query, page=1, size=20, packer=DefaultPacker()):
        self._query = query
        self._page = page
        self._size = size
        self._packer = packer

    def limit(self, page, size):
        self._page = page
        self._size = size
        return self

    def limit_from_request(self, request):
        page = max(int(request.get_argument("page", "1")), 1)
        size = int(request.get_argument("size", "20"))
        if size > self.MAX_PAGE_SIZE:
            size = self.MAX_PAGE_SIZE
        return self.limit(page, size)

    def data(self):
        total = self._query.count()
        items = self._query.offset((self._page - 1) * self._size).limit(self._size).all()

        return {
            "page": self._page,
            "size": self._size,
            "total": total,
            "items": [self._packer(item) for item in items]
        }


class ArgsPacker(RowPacker):
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __call__(self, row):
        return row.to_dict(**self.kwargs)
