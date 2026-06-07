print("简单计算器")
num1 = float(input("请输入第一个数字: "))
op = input("请输入运算符 (+, -, *, /): ")
num2 = float(input("请输入第二个数字: "))

if op == '+':
    result = num1 + num2
elif op == '-':
    result = num1 - num2
elif op == '*':
    result = num1 * num2
elif op == '/':
    if num2 == 0:
        print("错误：除数不能为零")
    else:
        result = num1 / num2
else:
    print("无效的运算符")

print("结果:", result)