User-Proxy
================

```bash
pip install --upgrade uv
uv sync --group=dev
bin/db_upgrade.sh
python run.py --port=8000 --logging=debug
```

inv
---

```bash
inv -l
inv web.serve
inv web.add-manager
inv web.add-role
inv web.modify-role
inv web.modify-user
inv web.list-users
inv web.list-roles
```

使用`inv --help`查看命令详细使用方法

- 添加系统管理员

系统管理员用于用户管理功能

`inv web.add-manager user_dn password`

- 修改角色

`inv web.add-or-modify-role name permission default`

1. name：权限名称
2. permission: json 字符串，比如：`{"autodoc_overall": ["normal"]}`
3. default： 字符串，是否设置为默认角色，`true`设置为默认，其他任意字符串为设置为非默认角色

- 修改用户

角色
---

默认普通用户的角色(Role.name == '默认角色')：

```json
{"calliper": ["normal"], "autodoc": ["normal"], "autodoc_overall": ["normal"], "scriber": ["remark", "browse"], "pdflux": ["normal"]}
```

默认管理员的角色(Role.name == '管理员')：

```json
{"calliper": ["admin"], "autodoc": ["admin"], "autodoc_overall": ["admin"], "scriber": ["remark", "browse", "manage_mold", "manage_prj", "manage_user", "table_identification"], "pdflux": ["admin"]}
```

其他子系统unify-login
===

其他子系统api推荐统一定义为 `/api/v1/user/unify-login`，子系统的auth信息配置在`unify_auth.auth_config`中。

从user-proxy统一验证后，向各个子系统进行token验证，并且以query-string的形式携带对应的用户数据。其中包含：

- ext_uname: 唯一的用户名信息(必须)
- _from: 来源信息，目前有`ldap`, `self`(本系统用户), `cas`(必须)
- ext_sys: 当前user-proxy部署环境(必须)
- username: 用户昵称(AutoDoc为必须字段)
- department: 部门名称
- department_id: 部门id

**每次新增客户部署时候需要检查各个子系统是否支持该客户用户的支持。**

#### 201909修改

新增:

- `permission`: 以`,`间隔的字符串
- `origin`: 可选，用于登录成功后跳转到原始url上

废弃:

- `_from`: 在ht分支依然使用

改动原因：

增加了trident进行用户，权限管理的功能，因此权限等数据需要从trident传递到各个子系统，各个子系统根据该字段进行设置各个子系统的用户权限

subpath功能的使用
---

subpath主要是用来在重定向的过程中，有以下几个可能：

1. trident跳转到trident
2. trident跳转到其他子系统
3. 其他子系统跳转到trident
4. 其他子系统跳转到自身

#### trident跳转到trident

配置在`webif.redirect_subpath`

#### trident跳转到其他子系统

配置在`unify_auth.auth_config`中，每个子系统都需要进行配置

#### 其他子系统跳转到trident

目前只有cms客户有这个跳转，配置在`webif.auth_cms.trident_subpath`

#### 其他子系统跳转到自身

配置在`webif.redirect_subpath`

#### 要注意的地方

host, subpath, path之间的组合使用了Python中的urljoin，这个函数有一些令人迷惑的地方：https://stackoverflow.com/questions/10893374/python-confusions-with-urljoin

所以我们约定如下：

1. host
    - 如果最后不是端口号的话，后面要加`/`，比如`http://www.example.com`不需要加`/`，但是`http://www.example.com/api/v1`需要加`/`
2. subpath
    - 前面不加`/`后面需要加`/`，比如`autodoc/`
3. path
    - 前面不加`/`，后面视实际情况加`/`（比如后面如果还要进行拼接，则需要加`/`）
    
总体原则就是按照stackoverflow中所说的理解方式，`urljoin(base, url)`中base是你所在的页面，url是页面中的anchor，点击url就会进行跳转。

API
===

#### 分析句子中的错别字

POST /api/v1/faulty-wordings

BODY JSON

```json
{
  "source_text": ""
}
```

#### 获取角色列表

GET /api/v1/roles

#### 创建角色

POST /api/v1/roles

BODY JSON

```json
{
    "name": "a",
    "permission": {
        "autodoc": ["admin"],
        "scriber": ["browse"]
    }
}
```

#### 修改角色

PUT /api/v1/roles/<role_id>

BODY JSON

```json
{
    "name": "a",
    "permission": {
        "autodoc": ["admin"],
        "scriber": ["browse"]
    }
}
```

#### 删除角色

DELETE /api/v1/roles/<role_id>

#### 获取单个角色

GET /api/v1/roles/<role_id>

#### 获取用户列表

GET /api/v1/users

#### 创建用户

POST /api/v1/users

BODY JSON

```json
{
    "uid": "a",
    "password": "B",
    "role_id": 1
}
```

#### 修改用户

PUT /api/v1/users/<user_id>

BODY JSON

```json
{
    "uid": "a",
    "password": "B",
    "role_id": 1
}
```

#### 删除用户

DELETE /api/v1/users/<user_id>

#### 获取单个用户

GET /api/v1/users/<user_id>

#### 获取子系统用户权限配置

GET /api/v1/system/permissions

#### CSRF token

GET /api/v1/csrf_token

### 直接登录

POST /api/v1/user/login

BODY(JSON)

```json
{
  "username": "",
  "password": ""
}
```

### 退出系统

GET /api/v1/user/logout

### 获取当前用户

GET /api/v1/user/me

### 已集成的系统

GET /api/v1/available-sys

```json
{
    "status": "ok",
    "data": {
        "autodoc": {
            "logout_api": "http://100.64.0.7:65178/api/v1/logout",
            "system": "autodoc"
        }
    }
}
```

### 前往系统

GET /api/v1/get-off

PARAMS

- sys

### ldap登录(HT环境)

POST /api/v1/user/ldap-login

BODY(JSON)

```json
{
  "uid": "",
  "password": "",
  "phone": 18723425678,  // 可选
  "auth_code": "123456",  // 可选
  "csrf_token": ""
}
```

### 检查用户名密码(HT环境)

POST /api/v1/user/check-auth

BODY(JSON)

```json
{
  "uid": "",
  "password": "",
  "csrf_token": ""
}
```

### 发送手机验证码(HT环境)

POST /api/v1/user/auth-code

BODY(JSON)

```json
{
  "phone": 18723425678,
  "csrf_token": ""
}
```

### 获取配置(HT环境)

GET /api/v1/feature

- response

```json
{
  "generate_auth_code": true
}

```

### CAS登录(CSC环境)

POST /api/v1/user/cas-login

### CAS登出(CSC环境)

POST /api/v1/user/cas-logout

### 单点登录(CMS环境)

GET /api/v1/cms/sso-login


### HT用户管理
用户新加Boolean字段，`is_admin` 和 `is_oa`。 只有管理员有用户管理功能，以下api均针对非oa用户

GET /api/v1/users   获取用户列表（require admin）

POST /api/v1/users  创建用户（require admin）
```
json {
    "uid": string,
    "password": string,
    "username": string,
    "department": string,
    "department_id": ''
}
```

PUT /api/v1/users/`user.id`/password   用户修改密码
```
json {
    'password': "新密码",
    'confirm_password': "旧密码"
}
```

PUT /api/v1/users/`user.id` 修改用户，json和创建相同 （require admin）

GET /api/v1/users/`user.id` 获取用户 （require admin）

DELETE /api/v1/users/`user.id`  删除用户（require admin，不能删自己）


GET /api/v1/user/search 搜索用户，（require admin）
支持参数：'ext_uname' 和 'username'
