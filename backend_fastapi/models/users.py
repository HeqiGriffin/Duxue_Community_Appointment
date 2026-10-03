from sqlalchemy import Column, Integer, String, Enum
from sqlalchemy.ext.declarative import declarative_base
import enum

Base = declarative_base()

class UserRole(str, enum.Enum):
    student = "student"
    admin = "admin"

class UserStatus(str, enum.Enum):
    normal = "normal"
    frozen = "frozen"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(String, unique=True, index=True, nullable=False) # 学号/工号作为唯一登录凭证
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.student)
    status = Column(Enum(UserStatus), default=UserStatus.normal)