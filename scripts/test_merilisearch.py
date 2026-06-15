import meilisearch




# curl -X POST 'http://localhost:7700/indexes/articles/documents' \
#   -H 'Authorization: Bearer 114514' \
#   -H 'Content-Type: application/json' \
#   --data-binary '[{"id":1,"title":"递归算法","content":"..."}]'


# curl 'http://localhost:7700/indexes/articles/search' \
#   -H 'Authorization: Bearer 114514' \
#   -H 'Content-Type: application/json' \
#   --data-binary '{"q":"递归"}'


# curl -X DELETE 'http://localhost:7700/indexes/articles/documents/1' \
#   -H 'Authorization: Bearer 114514'

# curl -X DELETE 'http://localhost:7700/indexes/articles' \
#   -H 'Authorization: Bearer 114514'

# 连接
client = meilisearch.Client('http://localhost:7700', '114514')

# 创建索引并添加文档
index = client.index('articles')
task = index.add_documents([
    {
        "id": 1,
        "title": "递归算法详解",
        "content": "递归是一种函数调用自身的编程技巧。递归算法通常包含两个部分：基准条件（base case）和递归步骤（recursive step）。基准条件用于终止递归，防止无限循环；递归步骤将问题分解为更小的子问题。经典的递归例子包括阶乘计算、斐波那契数列、汉诺塔问题和树的遍历。递归的优点是代码简洁、逻辑清晰，缺点是可能导致栈溢出和重复计算。可以通过尾递归优化和记忆化（memoization）来改善性能。",
        "tags": ["算法", "递归", "数据结构"],
        "view_count": 256
    },
    {
        "id": 2,
        "title": "Python 装饰器完全指南",
        "content": "装饰器是 Python 中一种强大的语法糖，本质上是一个接收函数作为参数并返回新函数的高阶函数。使用 @decorator 语法可以在不修改原函数代码的情况下扩展其功能。常见用途包括：日志记录、权限验证、缓存（如 @lru_cache）、重试机制和性能计时。装饰器可以带参数，也可以嵌套使用。类也可以作为装饰器，通过实现 __call__ 方法。functools.wraps 用于保留被装饰函数的元信息。",
        "tags": ["Python", "装饰器", "高阶函数"],
        "view_count": 189
    },
    {
        "id": 3,
        "title": "Docker 容器化入门到实践",
        "content": "Docker 是一种容器化技术，允许开发者将应用及其依赖打包到一个可移植的容器中。核心概念包括：镜像（Image）是只读模板，容器（Container）是镜像的运行实例，Dockerfile 定义构建镜像的步骤。常用命令有 docker build、docker run、docker compose。Docker Compose 用于定义和运行多容器应用。与虚拟机相比，Docker 更轻量、启动更快、资源占用更少。适合微服务架构、CI/CD 流水线和开发环境标准化。",
        "tags": ["Docker", "容器化", "运维", "DevOps"],
        "view_count": 342
    },
    {
        "id": 4,
        "title": "Git 版本控制最佳实践",
        "content": "Git 是分布式版本控制系统，每个开发者本地都有完整的仓库副本。核心工作流：git add 暂存更改，git commit 提交到本地，git push 推送到远程。分支策略推荐 Git Flow 或 Trunk-Based Development。常见技巧包括：git rebase 保持线性历史，git stash 临时保存更改，git cherry-pick 选择性合并提交，git bisect 二分查找引入 bug 的提交。.gitignore 用于排除不需要跟踪的文件。",
        "tags": ["Git", "版本控制", "协作开发"],
        "view_count": 412
    },
    {
        "id": 5,
        "title": "RESTful API 设计规范",
        "content": "REST 是一种架构风格，基于 HTTP 协议设计 Web API。核心原则：使用名词而非动词作为 URL（/users 而非 /getUsers），用 HTTP 方法表达操作（GET 查询、POST 创建、PUT 更新、DELETE 删除），返回适当的状态码（200 成功、201 创建、400 参数错误、404 未找到、500 服务器错误）。最佳实践包括：版本控制（/api/v1/）、分页（limit + offset）、过滤排序、HATEOAS 超媒体链接、统一错误格式。",
        "tags": ["API", "REST", "后端", "HTTP"],
        "view_count": 287
    },
    {
        "id": 6,
        "title": "机器学习入门：从线性回归到神经网络",
        "content": "机器学习是让计算机从数据中学习模式的技术。主要分为监督学习（有标签数据）、无监督学习（无标签数据）和强化学习（奖励反馈）。入门路径：先理解线性回归和逻辑回归，掌握梯度下降优化算法，然后学习决策树、随机森林、SVM 等经典算法，最后深入神经网络和深度学习。重要概念包括过拟合与正则化、交叉验证、特征工程、偏差-方差权衡。Python 生态中 scikit-learn 适合传统 ML，PyTorch/TensorFlow 适合深度学习。",
        "tags": ["机器学习", "AI", "深度学习", "Python"],
        "view_count": 523
    },
    {
        "id": 7,
        "title": "数据库索引原理与优化",
        "content": "数据库索引是提高查询速度的数据结构，最常用的是 B+ 树索引。索引的工作原理类似书籍目录，通过索引可以避免全表扫描。索引类型包括：主键索引、唯一索引、复合索引、全文索引和哈希索引。创建索引的原则：在 WHERE、JOIN、ORDER BY 频繁使用的列上建索引；避免在低基数列上建索引；复合索引注意最左前缀原则。索引的代价是占用额外存储空间，且会降低写入速度。使用 EXPLAIN 分析查询执行计划。",
        "tags": ["数据库", "SQL", "索引", "性能优化"],
        "view_count": 198
    },
    {
        "id": 8,
        "title": "Linux 常用命令速查手册",
        "content": "Linux 命令行是开发者必备技能。文件操作：ls、cd、cp、mv、rm、find、chmod。文本处理：cat、grep、sed、awk、sort、uniq、wc。进程管理：ps、top、htop、kill、nohup、systemctl。网络工具：curl、wget、ssh、scp、netstat、ping、traceroute。包管理：apt（Debian/Ubuntu）、yum/dnf（CentOS/Fedora）。实用技巧：管道符 | 串联命令、重定向 > 和 >>、后台运行 &、定时任务 crontab。",
        "tags": ["Linux", "命令行", "运维", "Shell"],
        "view_count": 678
    },
    {
        "id": 9,
        "title": "WebSocket 实时通信详解",
        "content": "WebSocket 是一种全双工通信协议，建立在 TCP 之上，通过一次 HTTP 握手升级为持久连接。与 HTTP 轮询相比，WebSocket 延迟更低、带宽占用更少。适用场景：实时聊天、在线游戏、股票行情、协同编辑、消息推送。Python 中可以用 websockets 库或 FastAPI 的 WebSocket 支持。前端使用原生 WebSocket API 或 Socket.IO 库。注意处理重连逻辑、心跳检测和消息序列化。生产环境建议配合 Nginx 做反向代理。",
        "tags": ["WebSocket", "实时通信", "网络", "前端"],
        "view_count": 145
    },
    # {
    #     "id": 10,
    #     "title": "设计模式：单例、工厂、观察者",
    #     "content": "设计模式是解决常见软件设计问题的可复用方案。创建型模式：单例模式确保类只有一个实例（数据库连接池）；工厂模式将对象创建逻辑封装，客户端无需关心具体类；建造者模式分步构建复杂对象。行为型模式：观察者模式定义一对多依赖关系（事件系统）；策略模式封装可互换的算法族；命令模式将请求封装为对象（撤销/重做）。结构型模式：适配器模式转换接口；装饰器模式动态添加职责；代理模式控制对象访问。",
    #     "tags": ["设计模式", "面向对象", "架构", "Python"],
    #     "view_count": 234
    # },
])
# 等待文档索引完成
client.wait_for_task(task.task_uid)

# 配置搜索设置
task = index.update_settings({
    'searchableAttributes': ['title', 'content', 'tags'],
    'filterableAttributes': ['tags', 'view_count'],
    'sortableAttributes': ['view_count'],
    'rankingRules': ['words', 'typo', 'proximity', 'attribute', 'sort', 'exactness']
})
# 等待所有异步任务完成
client.wait_for_task(task.task_uid)

# 搜索
results = index.search('递归')
print("搜索'递归':", [h['title'] for h in results['hits']])

# 带过滤的搜索
results = index.search('', {'filter': 'view_count > 60', 'sort': ['view_count:desc']})
print("view_count > 60 (按热度排序):", [(h['title'], h['view_count']) for h in results['hits']])

# Typo 容错：搜"递规"也能找到"递归"
results = index.search('递规')
print("Typo容错 搜'递规':", [h['title'] for h in results['hits']])