"""
File manager app package initialization
"""
from .database_postgresql import Base, db
from . import models

# 数据库初始化由应用启动时处理
# 不再在这里自动创建表 