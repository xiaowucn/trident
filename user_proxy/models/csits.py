from sqlalchemy import Column, Integer, String
from user_proxy.db import BaseModel


class CsitsTrack(BaseModel):
    __tablename__ = "csits_track"

    id = Column(Integer, primary_key=True)
    uuid = Column(String)
    event_time = Column(String)
    event = Column(String)
    system_code = Column(String)
    system_name = Column(String)
    account = Column(String)
    dept_id = Column(String)
    dept_name = Column(String)
    url = Column(String)
    path = Column(String)
