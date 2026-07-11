package main

import "github.com/some/lib"

type Service struct{}

func (s *Service) Process() {
    lib.Call()
    s.Save()
}

func (s *Service) Save() {}
