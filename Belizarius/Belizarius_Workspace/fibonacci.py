def fibonacci(n):
    if n <= 0:
        return "Input should be a positive integer."
    elif n == 1:
        return 0
    elif n == 2:
        return 1
    else:
        a, b = 0, 1
        for _ in range(3, n + 1):
            a, b = b, a + b
        return b

if __name__ == "__main__":
    try:
        num = int(input("Enter the value of n: "))
        print(f"The {num}th Fibonacci number is: {fibonacci(num)}")
    except ValueError:
        print("Please enter a valid integer.")
