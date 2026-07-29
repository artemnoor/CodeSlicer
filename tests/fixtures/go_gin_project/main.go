package main

type Router struct{}

func (r *Router) POST(path string, handler func()) {}

func CreateOrder() {}

func Configure(router *Router) {
	router.POST("/orders", CreateOrder)
}
