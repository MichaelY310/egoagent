# Smart Garden Controller — EgoAgent video fixture

This deliberately small Python repository is the safe recording workspace for EgoAgent. It contains two real bugs, deterministic tests, local research notes, and a workspace-scoped reusable Skill that should be discovered before a new one is created.

Start with:

```powershell
python -m unittest discover -v
```

The intended first task is:

> 修复智能花盆的浇水判断与单次用水量计算；不要修改公开函数签名。运行测试，并说明证据。
