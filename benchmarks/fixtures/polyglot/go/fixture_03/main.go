package orders3

import "github.com/gin-gonic/gin"

type Store3 struct{}
func (s *Store3) Save() {}
type Service3 struct{ store *Store3 }
func (s *Service3) Create() { s.store.Save() }
type Handler3 struct{ service *Service3 }
func (h *Handler3) Handle() { h.service.Create() }
func Routes3(r *gin.Engine, h *Handler3) { r.GET("/orders/3", h.Handle) }
