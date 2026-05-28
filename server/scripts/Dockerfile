FROM postgres:17

# 安装编译所需的依赖包
RUN apt-get update && apt-get install -y \
    build-essential \
    postgresql-server-dev-17 \
    git \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 1. 编译安装 scws (zhparser 的依赖)
RUN wget -q -O - http://www.xunsearch.com/scws/down/scws-1.2.3.tar.bz2 | tar xjf - \
    && cd scws-1.2.3 \
    && ./configure \
    && make install \
    && cd .. \
    && rm -rf scws-1.2.3

# 2. 编译安装 zhparser
RUN git clone https://github.com/amutu/zhparser.git \
    && cd zhparser \
    && make SCWS_HOME=/usr/local \
    && make install \
    && cd .. \
    && rm -rf zhparser

# 3. 编译安装 pgvector
RUN git clone --branch v0.8.0 https://github.com/pgvector/pgvector.git \
    && cd pgvector \
    && make \
    && make install \
    && cd .. \
    && rm -rf pgvector

# 清理编译依赖，保持镜像体积精简（可选，如果需要调试可以不删）
RUN apt-get purge -y --auto-remove build-essential postgresql-server-dev-17 git wget