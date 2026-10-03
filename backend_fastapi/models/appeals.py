from sqlalchemy import Column, Integer, String, ForeignKey, Enum, DateTime
from sqlalchemy.sql import func
import enum
from .users import Base

class AppealStatus(str, enum.Enum):
    pending = "pending"   # 待审核
    resolved = "resolved" # 已批准解封
    rejected = "rejected" # 驳回申诉，维持冻结

class Appeal(Base):
    __tablename__ = "appeals"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    reason = Column(String, nullable=False)              # 迟交/未交打扫照片的原因说明
    submit_time = Column(DateTime, default=func.now())
    status = Column(Enum(AppealStatus), default=AppealStatus.pending)
    admin_reply = Column(String, nullable=True)          # 管理员的处理批注意见