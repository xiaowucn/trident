from utensils.util import generate_timestamp
from wtforms import Form
from wtforms.fields import IntegerField, PasswordField, StringField
from wtforms.validators import DataRequired


class BaseUserLoginForm(Form):
    uid = StringField("uid", [DataRequired()])
    password = PasswordField("password", [DataRequired()])
    csrf_token = StringField("csrf_token", [DataRequired()])


class LDAPUserLoginForm(BaseUserLoginForm):
    phone = IntegerField('phone', default=0)
    auth_code = StringField('auth_code', default='')


class SysRequireForm(Form):
    sys = StringField("sys", [DataRequired()])
    start_utc = IntegerField("start_utc", [DataRequired()])
    end_utc = IntegerField("end_utc", [DataRequired()])
    project_name = StringField("project_name", [DataRequired()])
    reason = StringField("end_utc", default="")

    def validate_end_utc(self, field):
        if not field.data:
            raise ValueError("使用截止日期不能为空")
        if not self.start_utc.data or field.data < self.start_utc.data:
            raise ValueError("使用截止日期必须大于开始日期")
        if field.data < generate_timestamp():
            raise ValueError("使用截止日期不得早于当前")
        if field.data - self.start_utc.data > 14 * 24 * 60 * 60:
            raise ValueError("使用时间不得超过14天")
        return True


class PaginationForm(Form):
    page = IntegerField("page")
    size = IntegerField("size")

    def validate_page(self, field):
        if field.data is not None:
            if field.data < 1:
                raise ValueError("page should >= 1")
        else:
            field.data = 1
        return True

    def validate_size(self, field):
        if field.data is not None:
            if field.data > 20:
                raise ValueError("size should <= 20")
            if field.data < 0:
                raise ValueError("size should >= 0")
        else:
            field.data = 20
        return True


class DateSearchForm(PaginationForm):
    start_utc = IntegerField("start_utc")
    end_utc = IntegerField("end_utc")
