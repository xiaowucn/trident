# -*-coding:utf-8-*-
from sqlalchemy import Column, Integer, String
from user_proxy.db import BaseModel, db_session


class BusinessSystem(BaseModel):
    __tablename__ = 'business_system'

    id = Column(Integer, primary_key=True)
    name = Column(String)

    @property
    def code(self):
        return f'ZT_SYS000{self.id}'

    @classmethod
    def create(cls, name):
        model = cls(name=name)
        db_session.add(model)
        db_session.commit()
        return model

    def to_dict(self):
        return {'id': self.id, 'code': self.code, 'name': self.name}
