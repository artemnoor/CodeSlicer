package orders1

import "github.com/gin-gonic/gin"

type Store1 struct{}
func (s *Store1) Save() {}
type Service1 struct{ store *Store1 }
func (s *Service1) Create() { s.store.Save() }
type Handler1 struct{ service *Service1 }
func (h *Handler1) Handle() { h.service.Create() }
func Routes1(r *gin.Engine, h *Handler1) { r.GET("/orders/1", h.Handle) }
