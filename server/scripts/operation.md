1. 首次启动/重新编译
```
docker compose up -d --build
```
容器首次启动后需要激活插件
```
-- 安装中文分词
CREATE EXTENSION zhparser;

-- 创建文本搜索配置
CREATE TEXT SEARCH CONFIGURATION chinese (PARSER = zhparser);
ALTER TEXT SEARCH CONFIGURATION chinese ADD MAPPING FOR n,v,a,i,e,l,j WITH simple;

-- 测试中文分词（验证是否成功）
SELECT to_tsvector('chinese', '我喜欢使用PostgreSQL数据库');
```


2. 停止数据库
```
docker compose stop
```
3. 清空数据库
```
docker compose down
```
4. 重启数据库
```
docker compose up -d
```

5. 进入PostgreSQL命令行
```
docker exec -it pg17-vector-zhparser psql -U postgres -d ecommerce
```