def fibonacci(n):
    if n <= 0:
        return []
    elif n == 1:
        return [0]
    
    sequence = [0, 1]
    while len(sequence) < n:
        next_value = sequence[-1] + sequence[-2]
        sequence.append(next_value)
    
    return sequence

# Example usage to print the first 10 Fibonacci numbers
if __name__ == "__main__":
    n = 10
    print(f"The first {n} Fibonacci numbers are: {fibonacci(n)}")
