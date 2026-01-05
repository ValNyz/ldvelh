'use client';

import { forwardRef } from 'react';

const variants = {
	primary: 'bg-blue-600 hover:bg-blue-700 text-white',
	secondary: 'bg-gray-700 hover:bg-gray-600 text-white',
	danger: 'bg-red-700 hover:bg-red-600 text-white',
	ghost: 'bg-transparent hover:bg-gray-700 text-gray-300',
	outline: 'bg-transparent border border-gray-600 hover:bg-gray-700 text-gray-300',
};

const sizes = {
	sm: 'px-2 py-1 text-xs',
	md: 'px-4 py-2 text-sm',
	lg: 'px-6 py-3 text-base',
	icon: 'p-2',
};

const Button = forwardRef(({
	children,
	variant = 'primary',
	size = 'md',
	disabled = false,
	loading = false,
	className = '',
	...props
}, ref) => {
	const baseClasses = 'inline-flex items-center justify-center rounded font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-900 disabled:opacity-50 disabled:cursor-not-allowed';

	return (
		<button
			ref={ref}
			disabled={disabled || loading}
			className={`${baseClasses} ${variants[variant]} ${sizes[size]} ${className}`}
			{...props}
		>
			{loading && (
				<svg className="animate-spin -ml-1 mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24">
					<circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
					<path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
				</svg>
			)}
			{children}
		</button>
	);
});

Button.displayName = 'Button';

export default Button;

// Composants spécialisés
export function IconButton({ children, ...props }) {
	return (
		<Button size="icon" variant="ghost" {...props}>
			{children}
		</Button>
	);
}

export function DangerButton({ children, ...props }) {
	return (
		<Button variant="danger" {...props}>
			{children}
		</Button>
	);
}
